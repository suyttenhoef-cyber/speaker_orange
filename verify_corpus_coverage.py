"""
verify_corpus_coverage.py
-----------------
Outil de verification ponctuel (pas partie de l'application) : compare la
liste des articles presents dans un texte source brut (headers "Art. N.")
avec la liste des articles effectivement indexes dans le corpus, pour
detecter un trou d'extraction (ex. un titre entier saute par erreur).

Ne remplace pas une relecture humaine : un article peut apparaitre comme
"present" alors que son contenu est incomplet ou mal transcrit. Sert
uniquement a detecter les trous structurels (article absent du corpus).

Deuxieme verification : les references d'articles citees par les pratiques
validees (champ precise_ou_complete) qui ne pointent vers aucun article
existant dans le corpus - ce sont des references mortes, souvent le signe
qu'un article cite ailleurs n'a jamais ete indexe.

Usage:
    python3 verify_corpus_coverage.py Ressources_brutes/Ancien_code_civil_texte.md ancien_code_civil
"""
import json
import re
import sys
from pathlib import Path

CORPUS_FILES = [
    "corpus_par_matiere/corpus_etat_civil.json",
    "corpus_par_matiere/corpus_population.json",
    "corpus_par_matiere/corpus_etrangers.json",
]

ARTICLE_HEADER_RE = re.compile(r"Art\.\s?([0-9]+[a-zA-Z0-9/]*)\.")


def load_all_corpus():
    articles_by_doc = {}
    all_article_ids = set()
    pratiques = []
    for fp in CORPUS_FILES:
        d = json.loads(Path(fp).read_text(encoding="utf-8"))
        for a in d.get("articles", []):
            articles_by_doc.setdefault(a["document_id"], set()).add(a["numero"])
            all_article_ids.add(a["entry_id"])
        pratiques.extend(d.get("pratiques_validees", []))
    return articles_by_doc, all_article_ids, pratiques


def check_source_coverage(source_path, document_id):
    text = Path(source_path).read_text(encoding="utf-8")
    source_articles = sorted(set(ARTICLE_HEADER_RE.findall(text)))

    articles_by_doc, _, _ = load_all_corpus()
    corpus_numeros = articles_by_doc.get(document_id, set())

    missing = [n for n in source_articles if n not in corpus_numeros]

    print(f"Articles distincts dans {source_path}: {len(source_articles)}")
    print(f"Articles indexes pour '{document_id}': {len(corpus_numeros)}")
    print(f"Numeros absents du corpus: {len(missing)}")
    if missing:
        print("ATTENTION - verifier manuellement si ce sont des exclusions")
        print("volontaires (abroge / pure procedure judiciaire contentieuse)")
        print("ou un oubli d'extraction :")
        for n in missing:
            print(" ", n)
    return missing


def check_dangling_references():
    _, all_article_ids, pratiques = load_all_corpus()
    dangling = {}
    total_refs = 0
    for p in pratiques:
        for ref in p.get("precise_ou_complete") or []:
            total_refs += 1
            if ref not in all_article_ids:
                dangling.setdefault(ref, []).append(p["entry_id"])

    print(f"\nReferences precise_ou_complete au total: {total_refs}")
    print(f"References mortes (article inexistant): {sum(len(v) for v in dangling.values())}")
    for ref, users in sorted(dangling.items()):
        print(f"  {ref}  <-- cite par {users}")
    return dangling


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 verify_corpus_coverage.py <texte_source.md> <document_id>")
        sys.exit(1)

    missing = check_source_coverage(sys.argv[1], sys.argv[2])
    dangling = check_dangling_references()

    if missing or dangling:
        sys.exit(1)


if __name__ == "__main__":
    main()
