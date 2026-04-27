import hashlib
import math
import os
import re
import shutil
import subprocess

from .llm_client import get_embedding, query_llm

try:
    import pdfplumber
    HAS_PDF_PLUMBER = True
except ImportError:
    HAS_PDF_PLUMBER = False

try:
    import chromadb
    HAS_CHROMA = True
except ImportError:
    HAS_CHROMA = False


QUERY_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "for",
    "how",
    "in",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "use",
    "what",
    "when",
    "why",
    "with",
    "一下",
    "怎么",
    "什么",
    "如何",
    "解释",
}


def make_md_table(table_data):
    if not table_data:
        return ""
    md = ""
    for i, row in enumerate(table_data):
        clean_row = [str(cell).replace("\n", " ").strip() if cell else "" for cell in row]
        md += "| " + " | ".join(clean_row) + " |\n"
        if i == 0:
            md += "|" + "|".join(["---"] * len(clean_row)) + "|\n"
    return md


def get_rag_source_roots(ctx):
    selected = getattr(ctx, "rag_sources", None) or ["datasheets", "knowledge_base"]
    roots = []
    if "datasheets" in selected:
        roots.append(("datasheets", ctx.datasheet_dir))
    if "knowledge_base" in selected:
        roots.append(("knowledge_base", ctx.kb_dir))
    return roots


def iter_knowledge_files(ctx):
    roots = get_rag_source_roots(ctx)
    seen = set()
    for source_group, root in roots:
        if not root or not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [name for name in dirnames if name not in {"__pycache__", ".git"}]
            for fname in filenames:
                if not fname.lower().endswith((".txt", ".md", ".pdf")):
                    continue
                path = os.path.join(dirpath, fname)
                source_id = os.path.relpath(path, ctx.script_dir).replace("\\", "/")
                if source_id in seen:
                    continue
                seen.add(source_id)
                yield path, source_id, source_group


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def split_text_windows(text, max_chars=900, overlap=120):
    text = (text or "").strip()
    if len(text) <= max_chars:
        return [text] if text else []
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        window = text[start:end].strip()
        if window:
            chunks.append(window)
        if end == len(text):
            break
        start = max(0, end - overlap)
    return chunks


def normalize_text_content(content):
    content = re.sub(r"[ \t]+", " ", content or "")
    content = re.sub(r"\n{3,}", "\n\n", content)
    return content.strip()


def chunk_markdown_content(content):
    content = normalize_text_content(content)
    sections = []
    current_heading = ""
    current = []
    for line in content.splitlines():
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            if current:
                sections.append((current_heading, "\n".join(current).strip()))
            current_heading = heading.group(2).strip()
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append((current_heading, "\n".join(current).strip()))
    if not sections and content:
        sections = [("", content)]
    return sections


def chunk_text_content(content):
    content = normalize_text_content(content)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]
    chunks = []
    current = []
    current_len = 0
    for paragraph in paragraphs:
        if current and current_len + len(paragraph) > 900:
            chunks.append(("", "\n\n".join(current)))
            current = []
            current_len = 0
        if len(paragraph) > 1200:
            for part in split_text_windows(paragraph):
                chunks.append(("", part))
            continue
        current.append(paragraph)
        current_len += len(paragraph)
    if current:
        chunks.append(("", "\n\n".join(current)))
    return chunks


def build_text_chunks(path, source_id, source_group, content_hash):
    fname = os.path.basename(path)
    file_type = os.path.splitext(fname)[1].lower().lstrip(".")
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    sections = chunk_markdown_content(content) if file_type == "md" else chunk_text_content(content)
    chunk_texts, chunk_metas, chunk_ids = [], [], []
    mtime = str(int(os.path.getmtime(path)))
    chunk_index = 0
    for heading, section_text in sections:
        for part_index, text in enumerate(split_text_windows(section_text)):
            if len(text) <= 30:
                continue
            meta = {
                "source_file": fname,
                "source_id": source_id,
                "source_group": source_group,
                "file_type": file_type,
                "page": "N/A",
                "chunk_index": str(chunk_index),
                "chunk_type": "markdown_section" if file_type == "md" else "text",
                "heading": heading,
                "content_hash": content_hash,
                "mtime": mtime,
            }
            chunk_texts.append(text)
            chunk_metas.append(meta)
            chunk_ids.append(f"{source_id}_chunk_{chunk_index}_{part_index}")
            chunk_index += 1
    return chunk_texts, chunk_metas, chunk_ids


def build_pdf_chunks(path, source_id, source_group, content_hash):
    fname = os.path.basename(path)
    chunk_texts, chunk_metas, chunk_ids = [], [], []
    mtime = str(int(os.path.getmtime(path)))
    if not HAS_PDF_PLUMBER:
        return build_pdf_chunks_with_pdftotext(path, source_id, source_group, content_hash, mtime)
    print(f"  -> 正在使用 pdfplumber 提取 Markdown 表格: {fname}")
    try:
        with pdfplumber.open(path) as pdf:
            for page_num, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                table_settings = {"vertical_strategy": "text", "horizontal_strategy": "text"}
                tables = page.extract_tables(table_settings)
                combined_text = normalize_text_content(text)
                for part_index, chunk in enumerate(split_text_windows(combined_text)):
                    if len(chunk) <= 50:
                        continue
                    chunk_texts.append(chunk)
                    chunk_metas.append(
                        {
                            "source_file": fname,
                            "source_id": source_id,
                            "source_group": source_group,
                            "file_type": "pdf",
                            "page": str(page_num + 1),
                            "chunk_index": str(part_index),
                            "chunk_type": "pdf_page",
                            "heading": "",
                            "content_hash": content_hash,
                            "mtime": mtime,
                        }
                    )
                    chunk_ids.append(f"{source_id}_p{page_num + 1}_{part_index}")
                for table_index, table in enumerate(tables or []):
                    md_table = make_md_table(table)
                    if len(md_table.strip()) <= 30:
                        continue
                    chunk_texts.append(md_table.strip())
                    chunk_metas.append(
                        {
                            "source_file": fname,
                            "source_id": source_id,
                            "source_group": source_group,
                            "file_type": "pdf",
                            "page": str(page_num + 1),
                            "chunk_index": str(table_index),
                            "chunk_type": "pdf_table",
                            "table_index": str(table_index),
                            "heading": f"Table {table_index + 1}",
                            "content_hash": content_hash,
                            "mtime": mtime,
                        }
                    )
                    chunk_ids.append(f"{source_id}_p{page_num + 1}_table_{table_index}")
    except Exception as exc:
        print(f"  -> 读取 PDF 失败: {exc}")
    return chunk_texts, chunk_metas, chunk_ids


def build_pdf_chunks_with_pdftotext(path, source_id, source_group, content_hash, mtime=None):
    chunk_texts, chunk_metas, chunk_ids = [], [], []
    tool = shutil.which("pdftotext")
    if not tool:
        print(f"  -> 无法读取 PDF，缺少 pdfplumber 且未找到 pdftotext: {os.path.basename(path)}")
        return chunk_texts, chunk_metas, chunk_ids
    fname = os.path.basename(path)
    mtime = mtime or str(int(os.path.getmtime(path)))
    print(f"  -> 正在使用 pdftotext 提取 PDF 文本: {fname}")
    try:
        result = subprocess.run(
            [tool, "-layout", path, "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except Exception as exc:
        print(f"  -> pdftotext 读取 PDF 失败: {exc}")
        return chunk_texts, chunk_metas, chunk_ids
    if result.returncode != 0:
        print(f"  -> pdftotext 读取 PDF 失败: {result.stderr[-500:]}")
        return chunk_texts, chunk_metas, chunk_ids
    pages = result.stdout.split("\f")
    for page_num, page_text in enumerate(pages, start=1):
        page_text = normalize_text_content(page_text)
        for part_index, chunk in enumerate(split_text_windows(page_text)):
            if len(chunk) <= 50:
                continue
            chunk_texts.append(chunk)
            chunk_metas.append(
                {
                    "source_file": fname,
                    "source_id": source_id,
                    "source_group": source_group,
                    "file_type": "pdf",
                    "page": str(page_num),
                    "chunk_index": str(part_index),
                    "chunk_type": "pdf_page_text",
                    "heading": "",
                    "content_hash": content_hash,
                    "mtime": mtime,
                }
            )
            chunk_ids.append(f"{source_id}_p{page_num}_{part_index}")
    return chunk_texts, chunk_metas, chunk_ids


def build_chunks_for_file(path, source_id, source_group):
    content_hash = file_sha256(path)
    if path.lower().endswith(".pdf"):
        return build_pdf_chunks(path, source_id, source_group, content_hash)
    return build_text_chunks(path, source_id, source_group, content_hash)


def lexical_hash_embedding(text, dims=384):
    vector = [0.0] * dims
    tokens = tokenize_for_bm25(text)
    if not tokens:
        tokens = [token for token in re.findall(r"\S+", text or "") if token]
    if not tokens:
        return vector
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8", errors="ignore")).digest()
        idx = int.from_bytes(digest[:4], "big") % dims
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[idx] += sign
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def embed_chunks(chunk_texts, chunk_metas, chunk_ids, embedding_fn=None):
    embedding_fn = embedding_fn or get_embedding
    embeddings = []
    valid_texts = []
    valid_metas = []
    valid_ids = []
    skipped = 0
    for i, text in enumerate(chunk_texts):
        emb = embedding_fn(text)
        if not emb:
            emb = lexical_hash_embedding(text)
            skipped += 1
        embeddings.append(emb)
        valid_texts.append(text)
        valid_metas.append(chunk_metas[i])
        valid_ids.append(chunk_ids[i])
        if (i + 1) % 10 == 0:
            print(f"    - 向量化进度 {i + 1}/{len(chunk_texts)}")
    return embeddings, valid_texts, valid_metas, valid_ids, skipped


def extract_query_terms(query):
    clean_query = re.sub(r"[^\w\u4e00-\u9fa5]+", " ", (query or "").lower())
    terms = {word for word in clean_query.split() if len(word) >= 2 and word not in QUERY_STOPWORDS}
    for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]*", query or ""):
        lowered = token.lower()
        if len(lowered) >= 2 and lowered not in QUERY_STOPWORDS:
            terms.add(lowered)
    for i in range(len(clean_query) - 1):
        if "\u4e00" <= clean_query[i] <= "\u9fa5":
            term = clean_query[i:i + 2]
            if term not in QUERY_STOPWORDS:
                terms.add(term)
    for token in re.findall(r"\b[A-Z][A-Z0-9_-]{2,}\b", query or ""):
        terms.add(token.lower())
    return terms


def is_exact_technical_term(term):
    return bool(re.search(r"[\d_-]", term)) or term.upper() == term and len(term) >= 3


def keyword_match_score(text, meta, query_terms, skill_type="CONCEPT"):
    lowered = (text or "").lower()
    heading = (meta or {}).get("heading", "").lower()
    source_id = (meta or {}).get("source_id", "").lower()
    score = 0.0
    for term in query_terms:
        if not term:
            continue
        exact_pattern = rf"(?<![a-zA-Z0-9_]){re.escape(term)}(?![a-zA-Z0-9_])"
        exact_hits = len(re.findall(exact_pattern, lowered))
        if exact_hits:
            score += min(exact_hits, 3) * (0.3 if is_exact_technical_term(term) else 0.2)
        elif term in lowered:
            score += 0.08
        if term in heading:
            score += 0.35
        if term in source_id:
            score += 0.2
    if skill_type == "TABLE" and "|" in (text or ""):
        score += 0.3
    return score


def tokenize_for_bm25(text):
    text = (text or "").lower()
    tokens = re.findall(r"[a-z0-9_][a-z0-9_-]*|[\u4e00-\u9fa5]{2}", text)
    return [token for token in tokens if len(token) >= 2 and token not in QUERY_STOPWORDS]


def bm25_scores(documents, query_terms, k1=1.5, b=0.75):
    if not documents or not query_terms:
        return [0.0 for _ in documents]
    tokenized = [tokenize_for_bm25(doc) for doc in documents]
    doc_count = len(tokenized)
    avg_len = sum(len(tokens) for tokens in tokenized) / float(doc_count or 1)
    avg_len = avg_len or 1.0
    doc_freq = {}
    for tokens in tokenized:
        unique = set(tokens)
        for term in query_terms:
            if term in unique:
                doc_freq[term] = doc_freq.get(term, 0) + 1

    scores = []
    for tokens in tokenized:
        length = len(tokens) or 1
        freqs = {}
        for token in tokens:
            freqs[token] = freqs.get(token, 0) + 1
        score = 0.0
        for term in query_terms:
            tf = freqs.get(term, 0)
            if not tf:
                continue
            df = doc_freq.get(term, 0)
            idf = math.log(1.0 + (doc_count - df + 0.5) / (df + 0.5))
            denom = tf + k1 * (1.0 - b + b * length / avg_len)
            score += idf * (tf * (k1 + 1.0)) / denom
        scores.append(score)
    return scores


def source_label(meta):
    source_id = meta.get("source_id") or meta.get("source_file") or "unknown"
    page = meta.get("page") or "N/A"
    heading = meta.get("heading") or ""
    chunk_index = meta.get("chunk_index") or "?"
    parts = [source_id]
    if page != "N/A":
        parts.append(f"page {page}")
    if heading:
        parts.append(heading)
    parts.append(f"chunk {chunk_index}")
    return " | ".join(parts)


def merge_retrieval_results(vector_items, keyword_items, top_k):
    merged = {}
    for item in vector_items + keyword_items:
        key = item["id"]
        if key not in merged or item["score"] > merged[key]["score"]:
            merged[key] = item
        else:
            merged[key]["score"] += item["score"] * 0.1
    return sorted(merged.values(), key=lambda item: item["score"], reverse=True)[:top_k]


def cosine_similarity(left, right):
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left)) or 1.0
    right_norm = math.sqrt(sum(b * b for b in right)) or 1.0
    return dot / (left_norm * right_norm)


class InMemoryCollection:
    def __init__(self):
        self.ids = []
        self.documents = []
        self.metadatas = []
        self.embeddings = []

    def count(self):
        return len(self.documents)

    def add(self, embeddings, documents, metadatas, ids):
        self.embeddings.extend(embeddings)
        self.documents.extend(documents)
        self.metadatas.extend(metadatas)
        self.ids.extend(ids)

    def get(self, include=None):
        return {"ids": self.ids, "documents": self.documents, "metadatas": self.metadatas}

    def query(self, query_embeddings, n_results=20, include=None):
        query_embedding = query_embeddings[0] if query_embeddings else []
        scored = []
        for idx, embedding in enumerate(self.embeddings):
            similarity = cosine_similarity(query_embedding, embedding)
            scored.append((idx, similarity))
        scored.sort(key=lambda item: item[1], reverse=True)
        chosen = scored[:n_results]
        return {
            "ids": [[self.ids[idx] for idx, _ in chosen]],
            "documents": [[self.documents[idx] for idx, _ in chosen]],
            "metadatas": [[self.metadatas[idx] for idx, _ in chosen]],
            "distances": [[1.0 - similarity for _, similarity in chosen]],
        }


def retrieve_context(collection, query, skill_type="CONCEPT", top_k=5, candidate_k=20):
    query_terms = extract_query_terms(query)
    vector_items = []
    query_vec = get_embedding(query)
    if query_vec:
        results = collection.query(
            query_embeddings=[query_vec],
            n_results=max(candidate_k, top_k),
            include=["documents", "metadatas", "distances"],
        )
        docs = results["documents"][0]
        metas = results["metadatas"][0]
        distances = results["distances"][0]
        ids = results.get("ids", [[]])[0]
        for i, doc in enumerate(docs):
            meta = metas[i] or {}
            score = (1.0 - distances[i]) + keyword_match_score(doc, meta, query_terms, skill_type)
            vector_items.append(
                {
                    "id": ids[i] if i < len(ids) else f"vector_{i}",
                    "source": source_label(meta),
                    "text": doc,
                    "meta": meta,
                    "score": score,
                }
            )

    raw = collection.get(include=["documents", "metadatas"])
    raw_documents = raw.get("documents", []) or []
    raw_bm25_scores = bm25_scores(raw_documents, query_terms)
    keyword_items = []
    for i, doc in enumerate(raw_documents):
        meta = (raw.get("metadatas", []) or [{}])[i] or {}
        score = keyword_match_score(doc, meta, query_terms, skill_type) + raw_bm25_scores[i]
        if score > 0:
            keyword_items.append(
                {
                    "id": raw.get("ids", [])[i] if i < len(raw.get("ids", [])) else f"keyword_{i}",
                    "source": source_label(meta),
                    "text": doc,
                    "meta": meta,
                    "score": score,
                }
            )
    keyword_items.sort(key=lambda item: item["score"], reverse=True)
    keyword_items = keyword_items[: max(candidate_k, top_k)]
    return merge_retrieval_results(vector_items, keyword_items, top_k)


def format_retrieved_context(retrieved):
    return "\n\n".join(
        [f"[Source {idx + 1}: {item['source']} | score={item['score']:.3f}]\n{item['text']}" for idx, item in enumerate(retrieved)]
    )


def format_source_report(retrieved):
    if not retrieved:
        return "Sources: none"
    lines = ["Sources:"]
    for idx, item in enumerate(retrieved):
        lines.append(f"- [{idx + 1}] {item['source']} (score={item['score']:.3f})")
    return "\n".join(lines)


def summarize_index(collection):
    data = collection.get(include=["metadatas"])
    summary = {}
    for meta in data.get("metadatas", []) or []:
        source_id = meta.get("source_id") or meta.get("source_file") or "unknown"
        record = summary.setdefault(
            source_id,
            {
                "source_id": source_id,
                "source_group": meta.get("source_group", ""),
                "file_type": meta.get("file_type", ""),
                "content_hash": meta.get("content_hash", ""),
                "mtime": meta.get("mtime", ""),
                "chunks": 0,
            },
        )
        record["chunks"] += 1
        record["content_hash"] = meta.get("content_hash", record["content_hash"])
        record["mtime"] = meta.get("mtime", record["mtime"])
    return sorted(summary.values(), key=lambda item: item["source_id"])


def format_index_summary(summary):
    if not summary:
        return "RAG index is empty."
    lines = ["RAG Index:"]
    for item in summary:
        short_hash = (item.get("content_hash") or "")[:12]
        lines.append(
            "- {source_id} | chunks={chunks} | type={file_type} | group={source_group} | hash={hash} | mtime={mtime}".format(
                source_id=item["source_id"],
                chunks=item["chunks"],
                file_type=item.get("file_type", ""),
                source_group=item.get("source_group", ""),
                hash=short_hash,
                mtime=item.get("mtime", ""),
            )
        )
    return "\n".join(lines)


def format_dry_run_report(retrieved, max_chars=700):
    lines = [format_source_report(retrieved), "", "Retrieved Chunks:"]
    for idx, item in enumerate(retrieved):
        text = re.sub(r"\s+", " ", item.get("text", "")).strip()
        if len(text) > max_chars:
            text = text[:max_chars].rstrip() + "..."
        lines.append(f"\n[{idx + 1}] {item['source']} | score={item['score']:.3f}")
        lines.append(text)
    return "\n".join(lines)


def answer_has_source_citation(answer, source_count):
    if source_count <= 0:
        return True
    text = answer or ""
    for idx in range(1, source_count + 1):
        patterns = [
            rf"\[{idx}\]",
            rf"Source\s+{idx}\b",
            rf"来源\s*{idx}\b",
            rf"来源\s*\[{idx}\]",
        ]
        if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns):
            return True
    return False


def format_citation_warning(retrieved):
    return (
        "WARNING: RAG answer did not cite retrieved source numbers. "
        "Review the answer against these sources before using hardware facts.\n"
        + format_source_report(retrieved)
    )


def extract_answer_technical_terms(answer):
    terms = set()
    for token in re.findall(r"\b[A-Z][A-Z0-9_-]{2,}\b|\b[a-zA-Z_]+_[a-zA-Z0-9_]+\b", answer or ""):
        lowered = token.lower()
        if lowered not in QUERY_STOPWORDS:
            terms.add(lowered)
    return terms


def find_ungrounded_answer_terms(answer, retrieved):
    terms = extract_answer_technical_terms(answer)
    if not terms:
        return []
    context = "\n".join(item.get("text", "") for item in retrieved).lower()
    return sorted(term for term in terms if term not in context)


def format_grounding_warning(ungrounded_terms):
    if not ungrounded_terms:
        return ""
    return (
        "WARNING: RAG answer contains technical terms not found in retrieved chunks: "
        + ", ".join(ungrounded_terms)
    )


def build_or_load_vector_db(ctx):
    if not HAS_CHROMA:
        print("未安装 ChromaDB，请执行 `pip install chromadb`")
        return build_in_memory_collection(ctx)

    try:
        client = chromadb.PersistentClient(path=ctx.vector_db_dir)
    except Exception as exc:
        print(f"ChromaDB 打开失败，改用内存检索: {exc}")
        return build_in_memory_collection(ctx)
    if getattr(ctx, "rag_clear_index", False):
        try:
            client.delete_collection(name="fpga_knowledge")
        except Exception:
            pass

    collection = client.get_or_create_collection(name="fpga_knowledge", metadata={"hnsw:space": "cosine"})
    existing_data = collection.get(include=["metadatas"])
    existing_ids = existing_data.get("ids", []) if existing_data else []
    existing_metas = existing_data.get("metadatas", []) if existing_data else []
    ids_by_source = {}
    hash_by_source = {}
    for chunk_id, meta in zip(existing_ids, existing_metas):
        source_id = meta.get("source_id") or meta.get("source_file")
        if not source_id:
            continue
        ids_by_source.setdefault(source_id, []).append(chunk_id)
        hash_by_source.setdefault(source_id, meta.get("content_hash", ""))

    current_files = list(iter_knowledge_files(ctx))
    current_by_source = {source_id: (path, source_group) for path, source_id, source_group in current_files}
    stale_ids = []
    for source_id, chunk_ids in ids_by_source.items():
        if source_id not in current_by_source:
            stale_ids.extend(chunk_ids)
    if stale_ids:
        collection.delete(ids=stale_ids)
        print(f"已清理 {len(stale_ids)} 个过期文档片段。")

    files_to_index = []
    for path, source_id, source_group in current_files:
        current_hash = file_sha256(path)
        indexed_hash = hash_by_source.get(source_id)
        if getattr(ctx, "rag_reindex", False) or indexed_hash != current_hash:
            if source_id in ids_by_source:
                collection.delete(ids=ids_by_source[source_id])
                print(f"已删除变更文档旧索引: {source_id}")
            files_to_index.append((path, source_id, source_group))

    if files_to_index:
        print(f"\n发现 {len(files_to_index)} 个需要入库的文档，正在结构化解析并入库...")
        for path, source_id, source_group in files_to_index:
            chunk_texts, chunk_metas, chunk_ids = build_chunks_for_file(path, source_id, source_group)

            if chunk_texts:
                embeddings, valid_texts, valid_metas, valid_ids, skipped = embed_chunks(
                    chunk_texts, chunk_metas, chunk_ids
                )
                if skipped:
                    print(f"    - 跳过 {skipped} 个向量化失败的片段")
                if embeddings:
                    collection.add(embeddings=embeddings, documents=valid_texts, metadatas=valid_metas, ids=valid_ids)
        print("知识库结构化入库完成。\n")
    return collection


def build_in_memory_collection(ctx):
    collection = InMemoryCollection()
    files_to_index = list(iter_knowledge_files(ctx))
    if not files_to_index:
        return collection
    print(f"\n使用内存检索索引 {len(files_to_index)} 个文档...")
    for path, source_id, source_group in files_to_index:
        chunk_texts, chunk_metas, chunk_ids = build_chunks_for_file(path, source_id, source_group)
        if not chunk_texts:
            continue
        embeddings, valid_texts, valid_metas, valid_ids, skipped = embed_chunks(chunk_texts, chunk_metas, chunk_ids)
        if skipped:
            print(f"    - 使用本地兜底向量处理 {skipped} 个片段")
        collection.add(embeddings=embeddings, documents=valid_texts, metadatas=valid_metas, ids=valid_ids)
    return collection


def dump_rag_index(ctx):
    collection = build_or_load_vector_db(ctx)
    if not collection:
        print("RAG index unavailable.")
        return []
    summary = summarize_index(collection)
    print(format_index_summary(summary))
    return summary


def execute_rag_skill_legacy(ctx, query, skill_type):
    return execute_rag_skill(ctx, query, skill_type)


def execute_rag_skill(ctx, query, skill_type):
    collection = build_or_load_vector_db(ctx)
    if not collection or collection.count() == 0:
        print("知识库为空，请放入 PDF/TXT/MD 手册。")
        return

    print(f"\n[{skill_type} 专家] 正在混合检索知识库...")
    top_k = int(getattr(ctx, "rag_top_k", 5) or 5)
    candidate_k = int(getattr(ctx, "rag_candidate_k", 20) or 20)
    retrieved = retrieve_context(collection, query, skill_type=skill_type, top_k=top_k, candidate_k=candidate_k)
    if not retrieved:
        print("未检索到足够相关的知识片段。请补充 datasheets/ 或 knowledge_base/ 文档。")
        return

    context_str = format_retrieved_context(retrieved)
    source_report = format_source_report(retrieved)
    if getattr(ctx, "rag_show_sources", True):
        print(source_report)
    if getattr(ctx, "rag_dry_run", False):
        print(format_dry_run_report(retrieved))
        return

    if skill_type == "TABLE":
        prompt = f"""
        你是一个严谨的芯片硬件专家。只能根据以下参考手册片段回答问题。
        必须先定位 Markdown 表头，再提取目标数据行，并做到列名到数据的垂直映射。
        如果片段不足以回答，请明确说明缺少哪类文档或表格，不要编造参数。
        回答末尾必须列出使用的来源编号。

        【参考手册片段】\n{context_str}\n
        【用户问题】 {query}\n
        """
    else:
        prompt = f"""
        你是一个严谨的 FPGA 原理讲师。
        只能基于下方参考片段回答。如果文档没有提到，请诚实说明无法从当前知识库确认。
        涉及引脚、电压、时序、Vivado 命令、报错码、配置位等硬件事实时，必须引用来源编号。

        【参考片段】\n{context_str}\n
        【用户问题】 {query}\n
        """
    print("\n>>> [AI] 正在生成专业解答...")
    answer = query_llm(prompt)
    warnings = []
    if not answer_has_source_citation(answer, len(retrieved)):
        warnings.append(format_citation_warning(retrieved))
    grounding_warning = format_grounding_warning(find_ungrounded_answer_terms(answer, retrieved))
    if grounding_warning:
        warnings.append(grounding_warning)
    warning_text = ("\n\n" + "\n\n".join(warnings)) if warnings else ""
    print(
        "\n"
        + "=" * 65
        + f"\n[{skill_type} 专家解答报告]\n"
        + "=" * 65
        + f"\n{answer.strip()}{warning_text}\n\n{source_report}\n"
        + "=" * 65
        + "\n"
    )
