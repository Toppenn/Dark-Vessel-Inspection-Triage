from typing import Dict, Any, List

def validate_analyst_output(data: Dict[str, Any], dossier: Dict[str, Any]) -> List[str]:
    """
    Validates the LLM analyst JSON response against strict structural
    and data-integrity constraints before running main validation.
    """
    errors = []
    valid_ids = [d["id"] for d in dossier.get("inspection_candidates", [])]
    
    # Check required keys
    required_keys = ["prioritised_candidates", "ais_not_applicable", "observed_pattern", "overall_recommendation", "limitations"]
    for key in required_keys:
        if key not in data:
            errors.append(f"Missing required JSON key from analyst: '{key}'")
            
    # Validate prioritized candidates reference real IDs
    for candidate in data.get("prioritised_candidates", []):
        cand_id = candidate.get("id")
        if cand_id not in valid_ids:
            errors.append(f"Analyst hallucinated or referenced invalid ID not in candidates: '{cand_id}'")
            
    return errors