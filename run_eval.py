"""
run_eval.py
-----------
Harness d'evaluation notee du pipeline RAG. Rejoue le jeu de questions "gold"
(eval_gold_set.jsonl) a travers le pipeline reel (retrieval -> filtre
pratiques -> generation -> verification citation) et produit un score
reproductible - pour pouvoir dire objectivement "on est passe de X% a Y%"
au lieu de "ca semble mieux" a chaque changement (corpus, retrieval, prompt).

Deux modes :
- retrieval-only (par defaut, rapide/gratuit) : mesure uniquement le recall
  du retrieval (au moins un entry_id attendu est-il retrouve, avant et apres
  le filtre de pertinence ?). Ideal pour comparer deux strategies de
  retrieval (ex. vectoriel pur vs hybride) sans regenerer de reponses.
- --full : ajoute la generation de la reponse, les deux garde-fous de citation
  (check_citation_integrity : numero introuvable ; check_citation_relevance :
  numero reel mais mal applique - voir memoire
  misapplication_article_reel_voisin_distracteur), et un juge LLM qui evalue
  si la reponse respecte les criteres de reussite du gold set. Plus lent et
  plus couteux (3 appels LLM par question en plus de l'embedding), a reserver
  aux controles qualite periodiques.

Usage:
    python3 run_eval.py                                    # backend local, vectoriel, retrieval-only
    python3 run_eval.py --backend azure                    # backend Azure AI Search, vectoriel
    python3 run_eval.py --backend azure --mode hybrid      # + recherche hybride BM25+vecteur (RRF)
    python3 run_eval.py --backend azure --mode semantic    # + semantic ranker (cross-encoder)
    python3 run_eval.py --full                             # + generation/judge
    python3 run_eval.py --gold eval_gold_set.jsonl --out eval_report.json
"""
import argparse
import json
import sys
import time
from datetime import datetime

from openai import OpenAI

from rag_answer import (
    CHAT_MODEL,
    SYSTEM_PROMPT,
    build_user_message,
    check_citation_integrity,
    check_citation_relevance,
    embed_query,
    filter_applicable_practices,
    format_results_for_prompt,
)

NO_RESULTS_MESSAGE = (
    "Je n'ai trouve aucune information pertinente dans le corpus pour repondre "
    "a cette question."
)

JUDGE_SYSTEM_PROMPT = """Tu evalues si une reponse generee par un assistant RAG respecte des \
criteres de reussite donnes, pour une question posee par un agent de l'etat civil belge.

Reponds UNIQUEMENT avec un objet JSON : {"reussi": true ou false, "raison": "<une phrase courte>"}.
Sois strict sur le FOND (la reponse doit affirmer les faits corrects et ne pas affirmer le \
contraire des criteres), mais tolerant sur la FORME (formulation, longueur, style)."""


def load_gold(path):
    items = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def build_retriever(backend, embeddings_path):
    if backend == "local":
        from retrieve import Retriever
        return Retriever(embeddings_path)
    elif backend == "azure":
        from retrieve_azure_search import AzureSearchRetriever
        return AzureSearchRetriever()
    else:
        raise ValueError(f"backend inconnu: {backend}")


def _with_retry(fn, attempts=3, base_delay=2):
    """Le service Azure AI Search (tier gratuit partage) coupe parfois la
    connexion sans raison liee au code (ConnectionResetError) - on retente
    quelques fois avant d'abandonner plutot que de faire echouer tout le run
    pour un question sur 44."""
    last_exc = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:  # pylint: disable=broad-except
            last_exc = exc
            if attempt < attempts - 1:
                time.sleep(base_delay * (attempt + 1))
    raise last_exc


def search(retriever, backend, mode, client, query, top_k):
    # Pas de filtre par matiere : le bot en production ne restreint pas non
    # plus la recherche a une matiere donnee (une question peut legitimement
    # trouver sa reponse dans une autre matiere, ex. un article du Code DIP
    # cite pour une question d'etat civil). Le champ "matiere" du gold set
    # sert uniquement a regrouper les resultats dans le rapport.
    query_embedding = _with_retry(lambda: embed_query(client, query))
    if backend == "azure" and mode == "hybrid":
        # Fusion RRF BM25+vecteur - teste et ecarte (regression sur
        # eval_gold_set.jsonl : 90.2% vs 95.1% en vectoriel pur), conserve
        # pour comparaison/reproductibilite.
        return _with_retry(lambda: retriever.search_hybrid(query, query_embedding, top_k=top_k))
    if backend == "azure" and mode == "semantic":
        # Reranking par cross-encoder (semantic ranker Azure) sur le pool
        # hybride - voir retrieve_azure_search.search_semantic.
        return _with_retry(lambda: retriever.search_semantic(query, query_embedding, top_k=top_k))
    return _with_retry(lambda: retriever.search(query_embedding, top_k=top_k))


def entry_id_of(chunk_id):
    return chunk_id.split("::", 1)[1] if "::" in chunk_id else chunk_id


def recall_hit(results, expected_entry_ids):
    if not expected_entry_ids:
        return None  # pas de critere de retrieval pour cet item (verifie par le juge uniquement)
    found = {entry_id_of(meta["chunk_id"]) for _, meta in results}
    return any(e in found for e in expected_entry_ids)


def judge_answer(client, question, criteres, answer):
    user_msg = (
        f"Question posee : {question}\n\n"
        f"Criteres de reussite attendus : {criteres}\n\n"
        f"Reponse generee par l'assistant : {answer}"
    )
    completion = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    try:
        verdict = json.loads(completion.choices[0].message.content)
        return bool(verdict.get("reussi")), verdict.get("raison", "")
    except (json.JSONDecodeError, AttributeError):
        return None, "reponse du juge non parsable"


def run_item(client, retriever, backend, mode, item, top_k, full):
    question = item["question"]
    matiere = item.get("matiere")
    expected = item.get("expected_entry_ids", [])

    result = {"id": item["id"], "matiere": matiere, "question": question}

    raw_results = search(retriever, backend, mode, client, question, top_k)
    result["recall_raw"] = recall_hit(raw_results, expected)
    result["n_raw"] = len(raw_results)

    if not raw_results:
        result["recall_filtered"] = False if expected else None
        result["n_filtered"] = 0
        if full:
            result["answer"] = NO_RESULTS_MESSAGE
            result["unverified_citations"] = []
            result["relevance_issues"] = []
            result["judge_pass"] = not expected and item.get("criteres_reussite", "") == ""
        return result

    filtered_results, _ = filter_applicable_practices(client, question, raw_results)
    result["recall_filtered"] = recall_hit(filtered_results, expected)
    result["n_filtered"] = len(filtered_results)

    if not full:
        return result

    if not filtered_results:
        result["answer"] = NO_RESULTS_MESSAGE
        result["unverified_citations"] = []
        result["relevance_issues"] = []
        judge_pass, reason = judge_answer(client, question, item.get("criteres_reussite", ""), NO_RESULTS_MESSAGE)
        result["judge_pass"] = judge_pass
        result["judge_reason"] = reason
        return result

    context = format_results_for_prompt(filtered_results)
    user_message = build_user_message(context, question)
    completion = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0.1,
    )
    answer = completion.choices[0].message.content
    result["answer"] = answer
    result["unverified_citations"] = check_citation_integrity(filtered_results, answer)
    relevance_issues, _relevance_usage = check_citation_relevance(client, question, filtered_results, answer)
    result["relevance_issues"] = relevance_issues

    judge_pass, reason = judge_answer(client, question, item.get("criteres_reussite", ""), answer)
    result["judge_pass"] = judge_pass
    result["judge_reason"] = reason
    return result


def summarize(results, full):
    n = len(results)
    with_recall = [r for r in results if r["recall_raw"] is not None]

    def rate(key):
        vals = [r[key] for r in with_recall if r.get(key) is not None]
        return round(100 * sum(vals) / len(vals), 1) if vals else None

    summary = {
        "n_items": n,
        "n_items_with_retrieval_criteria": len(with_recall),
        "recall_raw_pct": rate("recall_raw"),
        "recall_filtered_pct": rate("recall_filtered"),
    }
    if full:
        clean_integrity = [r for r in results if not r.get("unverified_citations")]
        clean_relevance = [r for r in results if not r.get("relevance_issues")]
        judged = [r for r in results if r.get("judge_pass") is not None]
        summary["citations_integrity_clean_pct"] = round(100 * len(clean_integrity) / n, 1) if n else None
        summary["citations_relevance_clean_pct"] = round(100 * len(clean_relevance) / n, 1) if n else None
        summary["judge_pass_pct"] = (
            round(100 * sum(r["judge_pass"] for r in judged) / len(judged), 1) if judged else None
        )
        overall = [
            r for r in results
            if r.get("judge_pass")
            and not r.get("unverified_citations")
            and not r.get("relevance_issues")
            and (r["recall_filtered"] is not False)
        ]
        summary["overall_pass_pct"] = round(100 * len(overall) / n, 1) if n else None
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", default="eval_gold_set.jsonl")
    parser.add_argument("--out", default=None, help="chemin du rapport JSON (defaut: eval_report_<horodatage>.json)")
    parser.add_argument("--backend", choices=["local", "azure"], default="local")
    parser.add_argument("--mode", choices=["vector", "hybrid", "semantic"], default="vector",
                        help="strategie de retrieval (hybrid/semantic : backend azure uniquement)")
    parser.add_argument("--embeddings", default="embeddings.npz")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--full", action="store_true", help="ajoute generation + verif citation + juge LLM")
    parser.add_argument("--label", default=None, help="etiquette libre pour ce run, incluse dans le rapport")
    args = parser.parse_args()

    if args.mode != "vector" and args.backend != "azure":
        parser.error("--mode hybrid/semantic n'a de sens qu'avec --backend azure")

    client = OpenAI()
    retriever = build_retriever(args.backend, args.embeddings)
    gold = load_gold(args.gold)

    print(f"[run_eval] {len(gold)} questions - backend={args.backend} mode={args.mode} full={args.full}")

    results = []
    for i, item in enumerate(gold, 1):
        r = run_item(client, retriever, args.backend, args.mode, item, args.top_k, args.full)
        results.append(r)
        flag = "OK" if r["recall_filtered"] is not False else "MISS"
        print(f"  [{i}/{len(gold)}] {item['id']:8s} recall_filtered={r['recall_filtered']!s:5s} {flag}")

    summary = summarize(results, args.full)

    print("\n=== Resume ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")

    report = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "label": args.label,
        "backend": args.backend,
        "mode": args.mode,
        "full": args.full,
        "top_k": args.top_k,
        "summary": summary,
        "results": results,
    }
    out_path = args.out or f"eval_report_{args.backend}_{args.mode}{'_full' if args.full else ''}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nRapport ecrit dans {out_path}")

    misses = [r for r in results if r["recall_filtered"] is False]
    if misses:
        print(f"\n{len(misses)} question(s) sans le passage attendu apres filtre :")
        for r in misses:
            print(f"  - {r['id']}: {r['question'][:80]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
