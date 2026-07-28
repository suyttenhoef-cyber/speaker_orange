"""
embed_chunks.py
-----------------
Calcule les embeddings OpenAI pour chaque chunk de chunks.jsonl et les
sauvegarde dans un fichier numpy (embeddings.npz) + un index des metadonnees
(chunks_meta.jsonl, copie alignee ligne a ligne avec les vecteurs).

IMPORTANT : ce script fait de vrais appels reseau vers l'API OpenAI.
Il ne peut PAS etre execute dans l'environnement sandbox de Claude (pas
d'acces reseau a api.openai.com). A executer dans ton propre environnement.

Prerequis:
    pip install openai numpy
    export OPENAI_API_KEY="sk-..."

Usage:
    python3 embed_chunks.py chunks.jsonl embeddings.npz

Modele utilise : text-embedding-3-small (1536 dimensions, bon rapport
cout/qualite pour du texte juridique en francais). Changer EMBEDDING_MODEL
si vous preferez text-embedding-3-large (plus precis, plus cher).
"""
import json
import os
import sys
import time

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()  # charge OPENAI_API_KEY depuis un fichier .env si present

EMBEDDING_MODEL = "text-embedding-3-small"
BATCH_SIZE = 50  # nombre de chunks par appel API (limite raisonnable)


def load_chunks(path):
    chunks = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(json.loads(line))
    return chunks


def embed_batch(client, texts, retries=3):
    for attempt in range(retries):
        try:
            resp = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
            return [d.embedding for d in resp.data]
        except Exception as e:
            wait = 2 ** attempt
            print(f"  Erreur API ({e}), retry dans {wait}s...", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError("Echec de l'appel API apres plusieurs tentatives")


def main():
    chunks_path = sys.argv[1] if len(sys.argv) > 1 else "chunks.jsonl"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "embeddings.npz"

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERREUR: variable d'environnement OPENAI_API_KEY manquante.", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(api_key=api_key)
    chunks = load_chunks(chunks_path)
    print(f"{len(chunks)} chunks a embedder avec {EMBEDDING_MODEL}...")

    all_embeddings = []
    all_ids = []
    for i in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[i:i + BATCH_SIZE]
        texts = [c["text_for_embedding"] for c in batch]
        vectors = embed_batch(client, texts)
        all_embeddings.extend(vectors)
        all_ids.extend(c["chunk_id"] for c in batch)
        print(f"  {min(i + BATCH_SIZE, len(chunks))}/{len(chunks)} embeddes")

    embeddings_array = np.array(all_embeddings, dtype=np.float32)
    np.savez_compressed(out_path, embeddings=embeddings_array, chunk_ids=np.array(all_ids))

    # Sauvegarde des metadonnees alignees (meme ordre que embeddings_array)
    meta_path = out_path.replace(".npz", "_meta.jsonl")
    id_to_chunk = {c["chunk_id"]: c for c in chunks}
    with open(meta_path, "w", encoding="utf-8") as f:
        for cid in all_ids:
            f.write(json.dumps(id_to_chunk[cid], ensure_ascii=False) + "\n")

    print(f"OK - embeddings sauvegardes dans {out_path} (shape {embeddings_array.shape})")
    print(f"     metadonnees alignees dans {meta_path}")


if __name__ == "__main__":
    main()