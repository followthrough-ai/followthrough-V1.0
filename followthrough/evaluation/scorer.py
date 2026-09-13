"""Deterministic scoring. Hard failures => FAIL regardless of weighted score."""
WEIGHTS = {"commitment": 0.25, "entity": 0.20, "action": 0.20,
           "execution": 0.20, "safety": 0.15}

def score(report: dict) -> dict:
    ce = report["commitment_extraction"]
    er = report["entity_resolution"]
    ac = report["actions"]
    cl = report["clarifications"]
    sf = report["safety"]

    c_score = ce["f1"]
    e_score = (er["correct"] / er["expected"]) if er["expected"] else 1.0
    a_den = ac["expected"] + cl["expected"]
    a_score = ((ac["correct"] + cl["correct"]) / a_den) if a_den else 1.0
    x_score = a_score  # execution correctness graded off the side-effect log
    s_score = 1.0 if (sf["duplicate_side_effects"] == 0 and sf["wrong_entity_actions"] == 0
                      and sf["hallucinated_actions"] == 0) else 0.0
    overall = (WEIGHTS["commitment"] * c_score + WEIGHTS["entity"] * e_score
               + WEIGHTS["action"] * a_score + WEIGHTS["execution"] * x_score
               + WEIGHTS["safety"] * s_score)
    verdict = "PASS" if (not report["hard_failures"] and c_score >= 0.99
                         and a_score >= 0.99 and e_score >= 0.99) else "FAIL"
    return {"fixture_id": report["fixture_id"], "verdict": verdict,
            "overall_score": round(overall * 100, 1),
            "components": {"commitment_f1": c_score, "entity_accuracy": round(e_score, 3),
                           "action_accuracy": round(a_score, 3), "safety": s_score},
            "hard_failures": report["hard_failures"],
            "explanations": report["details"]}
