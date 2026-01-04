"""
Image Allocation Algorithm for Article Sections

Two-phase approach:
1. Compute relevance scores between all (section, image) pairs using LLM
2. Apply optimal assignment algorithm (Hungarian/Greedy) for fair distribution
"""
import logging
from typing import List, Dict, Any, Tuple
from collections import defaultdict

_LOGGER = logging.getLogger("article_agent.deep_agent.tools.image_allocator")


def compute_relevance_matrix(
    sections: List[Dict[str, Any]],
    images: List[Dict[str, Any]],
    llm_scorer=None
) -> Dict[Tuple[str, str], float]:
    """
    Phase 1: Compute relevance scores for all (section, image) pairs.
    
    Args:
        sections: List of section dicts with 'id', 'title', 'keywords'
        images: List of image dicts with 'element_id', 'visual_description'
        llm_scorer: Optional LLM-based scorer (if None, use keyword matching)
    
    Returns:
        Dict mapping (section_id, image_id) -> relevance score (0.0 to 1.0)
    """
    relevance_matrix = {}
    
    for sec in sections:
        sec_id = sec.get("id") or sec.get("section_id")
        sec_title = sec.get("title") or sec.get("heading") or ""
        sec_keywords = sec.get("keywords", [])
        sec_text = f"{sec_title} {' '.join(sec_keywords)}".lower()
        
        for img in images:
            img_id = img.get("element_id", "")
            img_desc = (img.get("visual_description") or img.get("content") or "").lower()
            
            # Simple keyword overlap scoring (can be replaced with embedding similarity)
            score = 0.0
            
            # Title match
            if sec_title.lower() in img_desc:
                score += 0.3
            
            # Keyword match
            keyword_matches = sum(1 for kw in sec_keywords if kw.lower() in img_desc)
            if keyword_matches > 0:
                score += min(0.5, keyword_matches * 0.15)
            
            # Content type bonus (diagrams, charts are generally valuable)
            if any(term in img_desc for term in ["架构", "流程", "图", "示意", "结构", "diagram", "chart", "architecture"]):
                score += 0.2
            
            # Normalize to 0-1
            score = min(1.0, score)
            
            relevance_matrix[(sec_id, img_id)] = score
    
    return relevance_matrix


def allocate_images_hungarian(
    sections: List[Dict[str, Any]],
    images: List[Dict[str, Any]],
    relevance_matrix: Dict[Tuple[str, str], float],
    max_images_per_section: int = 2,
    max_uses_per_image: int = 2
) -> Dict[str, List[str]]:
    """
    Phase 2: Optimal image allocation using Hungarian algorithm.
    
    Uses scipy.optimize.linear_sum_assignment for optimal bipartite matching.
    To handle multiple images per section and reuse constraints, we use
    a modified approach with virtual nodes.
    
    Args:
        sections: List of section dicts
        images: List of image dicts
        relevance_matrix: Pre-computed relevance scores
        max_images_per_section: Maximum images assigned to each section
        max_uses_per_image: Maximum times an image can be reused
    
    Returns:
        Dict mapping section_id -> List of assigned image_ids
    """
    try:
        import numpy as np
        from scipy.optimize import linear_sum_assignment
    except ImportError:
        _LOGGER.warning("scipy not available, falling back to greedy allocation")
        return _allocate_images_greedy(sections, images, relevance_matrix, 
                                        max_images_per_section, max_uses_per_image)
    
    section_ids = [s.get("id") or s.get("section_id") for s in sections]
    image_ids = [img.get("element_id") for img in images]
    
    n_sections = len(section_ids)
    n_images = len(image_ids)
    
    if n_images == 0:
        return {sec_id: [] for sec_id in section_ids}
    
    # Expand sections and images for multi-assignment
    # Each section appears max_images_per_section times
    # Each image appears max_uses_per_image times
    expanded_sections = []
    for sec_id in section_ids:
        for slot in range(max_images_per_section):
            expanded_sections.append((sec_id, slot))
    
    expanded_images = []
    for img_id in image_ids:
        for use in range(max_uses_per_image):
            expanded_images.append((img_id, use))
    
    n_rows = len(expanded_sections)  # Section slots
    n_cols = len(expanded_images)    # Image uses
    
    # Build cost matrix (Hungarian minimizes cost, so we use negative relevance)
    cost_matrix = np.zeros((n_rows, n_cols))
    
    for i, (sec_id, slot) in enumerate(expanded_sections):
        for j, (img_id, use) in enumerate(expanded_images):
            score = relevance_matrix.get((sec_id, img_id), 0.0)
            # Convert to cost (negative score for maximization)
            # Add small penalty for reuse (prefer first use)
            reuse_penalty = use * 0.01
            cost_matrix[i, j] = -(score - reuse_penalty)
    
    # Pad to square matrix if needed
    max_dim = max(n_rows, n_cols)
    if n_rows != n_cols:
        padded_cost = np.zeros((max_dim, max_dim))
        padded_cost[:n_rows, :n_cols] = cost_matrix
        cost_matrix = padded_cost
    
    _LOGGER.info(f"Running Hungarian algorithm on {n_rows}x{n_cols} cost matrix")
    
    # Run Hungarian algorithm
    row_ind, col_ind = linear_sum_assignment(cost_matrix)
    
    # Extract assignments
    allocation = {sec_id: [] for sec_id in section_ids}
    assigned_pairs = set()  # Track (sec_id, img_id) to avoid duplicates
    
    for row, col in zip(row_ind, col_ind):
        if row >= n_rows or col >= n_cols:
            continue  # Padding
        
        sec_id, slot = expanded_sections[row]
        img_id, use = expanded_images[col]
        
        # Check relevance threshold
        score = relevance_matrix.get((sec_id, img_id), 0.0)
        if score < 0.1:
            continue
        
        # Avoid duplicate (sec, img) pairs
        if (sec_id, img_id) in assigned_pairs:
            continue
        
        allocation[sec_id].append(img_id)
        assigned_pairs.add((sec_id, img_id))
        _LOGGER.debug(f"Hungarian assigned {img_id} to {sec_id} (score={score:.2f})")
    
    total_assigned = sum(len(v) for v in allocation.values())
    _LOGGER.info(f"Hungarian allocation complete: {total_assigned} assignments across {len(allocation)} sections")
    
    return allocation


def _allocate_images_greedy(
    sections: List[Dict[str, Any]],
    images: List[Dict[str, Any]],
    relevance_matrix: Dict[Tuple[str, str], float],
    max_images_per_section: int = 2,
    max_uses_per_image: int = 2
) -> Dict[str, List[str]]:
    """Fallback greedy allocation when scipy is not available."""
    from collections import defaultdict
    
    section_ids = [s.get("id") or s.get("section_id") for s in sections]
    allocation = defaultdict(list)
    image_usage = defaultdict(int)
    section_count = defaultdict(int)
    
    # Sort pairs by relevance
    pairs = [(score, sec_id, img_id) 
             for (sec_id, img_id), score in relevance_matrix.items() 
             if score > 0.1]
    pairs.sort(reverse=True)
    
    for score, sec_id, img_id in pairs:
        if section_count[sec_id] >= max_images_per_section:
            continue
        if image_usage[img_id] >= max_uses_per_image:
            continue
        if img_id in allocation[sec_id]:
            continue
        
        allocation[sec_id].append(img_id)
        section_count[sec_id] += 1
        image_usage[img_id] += 1
    
    return dict(allocation)


def allocate_images_for_article(
    sections: List[Dict[str, Any]],
    images: List[Dict[str, Any]],
    max_images_per_section: int = 2,
    max_uses_per_image: int = 2
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Main entry point for image allocation.
    
    Returns:
        Dict mapping section_id -> List of {id, desc} dicts
    """
    if not images:
        _LOGGER.warning("No images available for allocation")
        return {s.get("id") or s.get("section_id"): [] for s in sections}
    
    # Phase 1: Compute relevance matrix
    relevance_matrix = compute_relevance_matrix(sections, images)
    
    # Phase 2: Optimal allocation
    allocation = allocate_images_hungarian(
        sections, images, relevance_matrix,
        max_images_per_section=max_images_per_section,
        max_uses_per_image=max_uses_per_image
    )
    
    # Convert to output format with descriptions
    image_map = {img.get("element_id"): img for img in images}
    result = {}
    
    for sec_id, img_ids in allocation.items():
        result[sec_id] = []
        for img_id in img_ids:
            img = image_map.get(img_id, {})
            desc = img.get("visual_description") or img.get("content") or "无描述"
            # Truncate description
            desc_short = desc[:100] + "..." if len(desc) > 100 else desc
            result[sec_id].append({
                "id": img_id,
                "desc": desc_short
            })
    
    return result
