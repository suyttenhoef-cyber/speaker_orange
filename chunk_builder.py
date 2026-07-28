"""
chunk_builder.py
-----------------
Transforme le corpus structure (corpus_v4.json) en une liste plate de "chunks"
prets a etre embeddes. Un chunk = une unite retrievable (un article/paragraphe
de la Loi/AR/Loi organique, ou une section de la circulaire generale).

Regles de construction :
- Le texte embeddable combine : titre + contexte hierarchique + texte + exemples
  (les exemples sont inclus car ils aident souvent la recherche semantique,
  mais restent identifiables separement dans les metadonnees pour l'affichage).
- Chaque chunk garde une reference complete vers son document source
  (pour l'affichage de la citation : titre du texte, date, statut).
- Les entrees "historique_absorbe" sont chunkees mais marquees, pour permettre
  un filtre au moment de la recherche (par defaut : exclues des reponses
  "etat du droit actuel").
- Les entrees "pratiques_validees" (cle optionnelle du corpus) sont des
  clarifications de terrain validees par un expert, pas des textes officiels -
  chunkees avec un statut_entree="reference_interne" distinct pour que le
  prompt systeme (cf. rag_answer.py) les cite comme telles.

Usage:
    python3 chunk_builder.py corpus_par_matiere/ chunks.jsonl
    (ou sur un seul fichier : python3 chunk_builder.py corpus_amu.json chunks.jsonl)
"""
import json
import sys
from pathlib import Path


def load_corpus(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def doc_lookup(corpus):
    return {d["document_id"]: d for d in corpus["documents"]}


def build_chunk_text(entry, is_circulaire=False):
    """Construit le texte qui sera envoye a l'API d'embedding."""
    parts = []
    if is_circulaire:
        parts.append(f"[{entry.get('chapitre_parent', '')}] {entry.get('titre', '')}")
    else:
        parts.append(f"[{entry.get('emplacement', '')}] {entry.get('titre_contexte', '')}")
    parts.append(entry.get("texte", "") or entry.get("texte_original", ""))

    exemples = entry.get("exemples") or []
    if exemples:
        parts.append("Exemples illustratifs : " + " | ".join(exemples))

    jurisprudence = entry.get("jurisprudence_citee") or []
    if jurisprudence:
        parts.append("Jurisprudence citee : " + " ; ".join(jurisprudence))

    return "\n\n".join(p for p in parts if p)


def build_chunks(corpus):
    docs = doc_lookup(corpus)
    chunks = []
    matiere = corpus.get("_matiere", "aide_sociale_generale")  # retro-compat anciens fichiers

    # --- Articles (Loi, AR, Loi organique) ---
    for entry in corpus.get("articles", []):
        doc = docs.get(entry["document_id"], {})
        chunk = {
            "chunk_id": f"{matiere}::{entry['entry_id']}",
            "matiere": matiere,
            "document_id": entry["document_id"],
            "document_titre": doc.get("titre"),
            "document_type": doc.get("type"),
            "document_date": doc.get("date_texte"),
            "document_statut": doc.get("statut"),
            "numero": entry.get("numero"),
            "titre_contexte": entry.get("titre_contexte"),
            "categorie": entry.get("categorie"),
            "sous_categorie": entry.get("sous_categorie"),
            "statut_entree": entry.get("statut", doc.get("statut")),
            "commente_par": entry.get("commente_par", []),
            "articles_lies": entry.get("articles_lies", []),
            "flag_recent": entry.get("flag_recent", False),
            "text_for_embedding": build_chunk_text(entry, is_circulaire=False),
        }
        chunks.append(chunk)

    # --- Sections de circulaire en vigueur ---
    for entry in corpus.get("sections_circulaire", []):
        doc = docs.get(entry["document_id"], {})
        if entry.get("statut_extraction") == "a_completer":
            continue  # rien a indexer, pas encore de contenu reel
        chunk = {
            "chunk_id": f"{matiere}::{entry['entry_id']}",
            "matiere": matiere,
            "document_id": entry["document_id"],
            "document_titre": doc.get("titre"),
            "document_type": doc.get("type"),
            "document_date": doc.get("date_texte"),
            "document_statut": doc.get("statut"),
            "numero": entry.get("numero_section"),
            "titre_contexte": entry.get("titre"),
            "categorie": entry.get("categorie"),
            "sous_categorie": entry.get("sous_categorie"),
            "statut_entree": doc.get("statut"),
            "articles_references": entry.get("articles_references", []),
            "text_for_embedding": build_chunk_text(entry, is_circulaire=True),
        }
        chunks.append(chunk)

    # --- Sections de circulaire absorbee (historique) ---
    for entry in corpus.get("sections_circulaire_absorbee", []):
        doc = docs.get(entry["document_id"], {})
        chunk = {
            "chunk_id": f"{matiere}::{entry['entry_id']}",
            "matiere": matiere,
            "document_id": entry["document_id"],
            "document_titre": doc.get("titre"),
            "document_type": doc.get("type"),
            "document_date": doc.get("date_texte"),
            "document_statut": "historique_absorbe",
            "numero": entry.get("numero_section"),
            "titre_contexte": entry.get("titre"),
            "categorie": entry.get("categorie"),
            "sous_categorie": entry.get("sous_categorie"),
            "statut_entree": "historique_absorbe",
            "absorbe_par": entry.get("absorbe_par"),
            "text_for_embedding": build_chunk_text(entry, is_circulaire=True),
        }
        chunks.append(chunk)

    # --- Pratiques validees : clarifications de terrain validees par un
    # expert juridique interne, comblant une zone d'ombre des textes
    # officiels. Ce ne sont PAS des textes legaux/circulaires - marquees
    # avec un statut distinct pour que le prompt systeme les cite comme
    # telles plutot que comme une source officielle. ---
    for entry in corpus.get("pratiques_validees", []):
        doc = docs.get(entry["document_id"], {})
        parts = [f"[Pratique validee] {entry.get('titre', '')}"]
        if entry.get("date_reponse"):
            parts.append(f"Date de la reponse : {entry['date_reponse']}")
        if entry.get("alerte_obsolescence"):
            parts.append(f"ATTENTION - POTENTIELLEMENT OBSOLETE : {entry['alerte_obsolescence']}")
        if entry.get("question_origine"):
            parts.append(f"Question d'origine : {entry['question_origine']}")
        parts.append(entry.get("texte", ""))
        chunk = {
            "chunk_id": f"{matiere}::{entry['entry_id']}",
            "matiere": matiere,
            "document_id": entry["document_id"],
            "document_titre": doc.get("titre"),
            "document_type": doc.get("type"),
            "document_date": doc.get("date_texte"),
            "document_statut": doc.get("statut"),
            "numero": entry.get("code"),
            "titre_contexte": entry.get("titre"),
            "categorie": entry.get("categorie"),
            "sous_categorie": entry.get("sous_categorie"),
            "statut_entree": "reference_interne",
            "date_reponse": entry.get("date_reponse"),
            "alerte_obsolescence": entry.get("alerte_obsolescence"),
            "precise_ou_complete": entry.get("precise_ou_complete", []),
            "source_validation": entry.get("source_validation"),
            "text_for_embedding": "\n\n".join(p for p in parts if p),
        }
        chunks.append(chunk)

    return chunks


def main():
    """
    Usage:
        python3 chunk_builder.py <fichier.json OU dossier/> chunks.jsonl

    Si le premier argument est un dossier, tous les fichiers *.json qu'il
    contient sont charges et fusionnes (un fichier = une matiere, cf. le
    champ _matiere dans chaque fichier).
    """
    in_path = sys.argv[1] if len(sys.argv) > 1 else "corpus/"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "chunks.jsonl"

    all_chunks = []
    in_path_obj = Path(in_path)

    if in_path_obj.is_dir():
        json_files = sorted(in_path_obj.glob("*.json"))
        if not json_files:
            print(f"ERREUR: aucun fichier .json trouve dans {in_path}", file=sys.stderr)
            sys.exit(1)
        for jf in json_files:
            corpus = load_corpus(jf)
            matiere = corpus.get("_matiere", jf.stem)
            chunks = build_chunks(corpus)
            all_chunks.extend(chunks)
            print(f"  {jf.name}: {len(chunks)} chunks (matiere: {matiere})")
    else:
        corpus = load_corpus(in_path)
        all_chunks = build_chunks(corpus)

    with open(out_path, "w", encoding="utf-8") as f:
        for c in all_chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    n_actifs = sum(1 for c in all_chunks if c["statut_entree"] != "historique_absorbe")
    n_hist = sum(1 for c in all_chunks if c["statut_entree"] == "historique_absorbe")
    print(f"OK - {len(all_chunks)} chunks ecrits dans {out_path}")
    print(f"  dont {n_actifs} actifs (en_vigueur) et {n_hist} historiques (absorbes)")

    lengths = [len(c["text_for_embedding"]) for c in all_chunks]
    print(f"  longueur texte: min={min(lengths)} max={max(lengths)} moyenne={sum(lengths)//len(lengths)} caracteres")


if __name__ == "__main__":
    main()