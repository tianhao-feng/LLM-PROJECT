import os
import re

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


def iter_knowledge_files(ctx):
    roots = [ctx.datasheet_dir, ctx.kb_dir]
    seen = set()
    for root in roots:
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
                yield path, source_id


def embed_chunks(chunk_texts, chunk_metas, chunk_ids, embedding_fn=None):
    embedding_fn = embedding_fn or get_embedding
    embeddings = []
    valid_texts = []
    valid_metas = []
    valid_ids = []
    skipped = 0
    for i, text in enumerate(chunk_texts):
        emb = embedding_fn(text)
        if emb:
            embeddings.append(emb)
            valid_texts.append(text)
            valid_metas.append(chunk_metas[i])
            valid_ids.append(chunk_ids[i])
        else:
            skipped += 1
        if (i + 1) % 10 == 0:
            print(f"    - 向量化进度 {i + 1}/{len(chunk_texts)}")
    return embeddings, valid_texts, valid_metas, valid_ids, skipped


def build_or_load_vector_db(ctx):
    if not HAS_CHROMA:
        print("未安装 ChromaDB，请执行 `pip install chromadb`")
        return None

    client = chromadb.PersistentClient(path=ctx.vector_db_dir)
    collection = client.get_or_create_collection(name="fpga_knowledge", metadata={"hnsw:space": "cosine"})
    existing_data = collection.get(include=["metadatas"])
    indexed_files = set()
    if existing_data and existing_data["metadatas"]:
        indexed_files = set(meta.get("source_id") or meta.get("source_file") for meta in existing_data["metadatas"])
    new_files = [(path, source_id) for path, source_id in iter_knowledge_files(ctx) if source_id not in indexed_files]

    if new_files:
        print(f"\n发现 {len(new_files)} 个新文档，正在结构化解析并入库...")
        for path, source_id in new_files:
            fname = os.path.basename(path)
            chunk_texts, chunk_metas, chunk_ids = [], [], []
            if fname.lower().endswith(".pdf") and HAS_PDF_PLUMBER:
                print(f"  -> 正在使用 pdfplumber 提取 Markdown 表格: {fname}")
                try:
                    with pdfplumber.open(path) as pdf:
                        for page_num, page in enumerate(pdf.pages):
                            text = page.extract_text() or ""
                            table_settings = {"vertical_strategy": "text", "horizontal_strategy": "text"}
                            tables = page.extract_tables(table_settings)
                            md_tables = "\n\n".join([make_md_table(t) for t in tables if t])
                            combined_text = (text + "\n\n" + md_tables).strip()
                            if len(combined_text) > 50:
                                chunk_texts.append(combined_text)
                                chunk_metas.append({"source_file": fname, "source_id": source_id, "page": str(page_num + 1)})
                                chunk_ids.append(f"{source_id}_p{page_num + 1}")
                except Exception as exc:
                    print(f"  -> 读取 PDF 失败: {exc}")
            elif fname.lower().endswith((".txt", ".md")):
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                content = re.sub(r"[ \t]+", " ", content)
                content = re.sub(r"\n{3,}", "\n\n", content)
                for i in range(0, len(content), 600):
                    text = content[i:i + 800].strip()
                    if len(text) > 30:
                        chunk_texts.append(text)
                        chunk_metas.append({"source_file": fname, "source_id": source_id, "page": "N/A"})
                        chunk_ids.append(f"{source_id}_chunk_{i}")

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


def execute_rag_skill(ctx, query, skill_type):
    collection = build_or_load_vector_db(ctx)
    if not collection or collection.count() == 0:
        print("知识库为空，请放入 PDF/TXT/MD 手册。")
        return

    print(f"\n[{skill_type} 专家] 正在混合检索知识库...")
    query_vec = get_embedding(query)
    if not query_vec:
        print("向量化失败。")
        return

    results = collection.query(query_embeddings=[query_vec], n_results=20, include=["documents", "metadatas", "distances"])
    docs, metas, distances = results["documents"][0], results["metadatas"][0], results["distances"][0]
    clean_query = re.sub(r"[^\w\u4e00-\u9fa5]+", " ", query.lower())
    query_words = set(clean_query.split())
    for i in range(len(clean_query) - 1):
        if "\u4e00" <= clean_query[i] <= "\u9fa5":
            query_words.add(clean_query[i:i + 2])

    retrieved = []
    for i in range(len(docs)):
        keyword_score = sum(0.15 for w in query_words if w in docs[i].lower() and len(w) >= 2)
        score = (1.0 - distances[i]) + keyword_score
        retrieved.append({"source": f"{metas[i]['source_file']} (Page {metas[i]['page']})", "text": docs[i], "score": score})
    retrieved.sort(key=lambda x: x["score"], reverse=True)
    context_str = "\n".join([f"【来源 {c['source']}】\n{c['text']}" for c in retrieved[:5]])

    if skill_type == "TABLE":
        prompt = f"""
        你是一个严谨的芯片硬件专家。请根据以下参考手册片段回答问题。
        必须先定位 Markdown 表头，再提取目标数据行，并做列名到数据的垂直映射。

        【参考手册片段】\n{context_str}\n
        【用户问题】 {query}\n
        """
    else:
        prompt = f"""
        你是一个严谨的 FPGA 原理讲师。
        只能基于下方参考片段回答。如果文档没有提到，请诚实拒答。

        【参考片段】\n{context_str}\n
        【用户问题】 {query}\n
        """
    print("\n>>> [AI] 正在生成专业解答...")
    answer = query_llm(prompt)
    print("\n" + "=" * 65 + f"\n[{skill_type} 专家解答报告]\n" + "=" * 65 + f"\n{answer.strip()}\n" + "=" * 65 + "\n")
