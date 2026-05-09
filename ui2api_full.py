import json, sys, urllib.request, re, argparse

UI_ONLY = {"Note", "MarkdownNote", "JWNote"}
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

def _is_widget_type(itype):
    return isinstance(itype, list) or itype in ("STRING", "INT", "FLOAT", "BOOLEAN")
COMFYUI = "http://localhost:8188"

_obj_cache = {}
def obj_info(ntype):
    if ntype not in _obj_cache:
        with urllib.request.urlopen(f"{COMFYUI}/object_info/{ntype}", timeout=10) as r:
            _obj_cache[ntype] = json.loads(r.read())[ntype]
    return _obj_cache[ntype]

def resolve_node_inputs(node, info, link_map, prefix=""):
    """Resolve a node's inputs from widget_values and links.
    link_map: {link_id: [source_node_id_str, source_slot]}
    prefix: non-empty string for inner subgraph nodes (to prefix their referenced IDs)
    """
    required = info.get("input", {}).get("required", {})
    optional = info.get("input", {}).get("optional", {}) or {}
    schema_map = {}
    schema_map.update(required)
    schema_map.update(optional)

    wv = list(node.get("widgets_values", []))
    inputs = {}
    wi = 0
    handled = set()

    # Pass 1: process the node's inputs array in order.
    # This correctly handles COMFY_DYNAMICCOMBO_V3 / COMFY_AUTOGROW_V3 sub-inputs
    # whose widget slots appear in widgets_values but not in the top-level schema.
    for inp_def in node.get("inputs", []):
        name = inp_def.get("name", "")
        lid = inp_def.get("link")
        is_widget = "widget" in inp_def
        handled.add(name)

        if is_widget:
            # Widget entry — always consumes a wv slot regardless of link
            schema = schema_map.get(name)
            imeta = (schema[1] if schema and len(schema) > 1
                     and isinstance(schema[1], dict) else {})
            if lid is not None and lid in link_map:
                inputs[name] = link_map[lid]
            elif wi < len(wv):
                inputs[name] = wv[wi]
            wi += 1
            if imeta.get("control_after_generate"):
                wi += 1
        else:
            # Pure connection (no widget key) — no wv slot consumed
            if lid is not None and lid in link_map:
                inputs[name] = link_map[lid]

    # Pass 2: handle schema entries not present in the inputs array
    # (nodes that store all widget values in widgets_values without inputs entries)
    for name in list(required.keys()) + list(optional.keys()):
        if name in handled:
            continue
        schema = schema_map[name]
        itype = schema[0] if schema else None
        imeta = schema[1] if len(schema) > 1 and isinstance(schema[1], dict) else {}
        if itype == "*":
            continue
        if itype is not None and _is_widget_type(itype):
            if wi < len(wv):
                inputs[name] = wv[wi]
                wi += 1
                if imeta.get("control_after_generate"):
                    wi += 1
    return inputs

def _resolve_reroutes(sub_nodes, inner_links):
    """Build {reroute_node_id: (real_origin_id, real_origin_slot)} by following chains."""
    reroute_ids = {n["id"] for n in sub_nodes if n["type"] == "Reroute"}
    if not reroute_ids:
        return {}
    # Map (target_id, target_slot) → (origin_id, origin_slot)
    link_src = {}
    for l in inner_links:
        link_src[(l["target_id"], l["target_slot"])] = (l["origin_id"], l["origin_slot"])

    resolved = {}
    def resolve(nid, visited=None):
        if nid in resolved:
            return resolved[nid]
        if visited is None:
            visited = set()
        if nid in visited:
            return None
        visited.add(nid)
        src = link_src.get((nid, 0))
        if src is None:
            return None
        origin_id, origin_slot = src
        if origin_id in reroute_ids:
            r = resolve(origin_id, visited)
            resolved[nid] = r
            return r
        elif origin_id == -10:
            resolved[nid] = (-10, origin_slot)
            return resolved[nid]
        else:
            resolved[nid] = (origin_id, origin_slot)
            return resolved[nid]

    for rid in reroute_ids:
        resolve(rid)
    return resolved

def expand_subgraph(outer_node, sub, subgraph_defs, prefix=None, outer_lmap=None):
    """Expand a subgraph UUID node into flat API-format nodes (recursive).
    Returns (new_nodes_dict, output_slot_map).
    output_slot_map: {outer_output_slot: [prefixed_inner_node_id, inner_slot]}
    Handles Reroute passthrough, mode=4 bypass, and nested UUID subgraphs.
    outer_lmap: {link_id: [source_node_id_str, source_slot]} for resolving -10 origins.
    """
    if prefix is None:
        prefix = str(outer_node["id"]) + "_"
    if outer_lmap is None:
        outer_lmap = {}
    inner_links = sub["links"]

    reroute_map = _resolve_reroutes(sub["nodes"], inner_links)
    reroute_ids = {n["id"] for n in sub["nodes"] if n["type"] == "Reroute"}
    bypassed_ids = {n["id"] for n in sub["nodes"] if n.get("mode", 0) == 4}
    uuid_inner_ids = {n["id"] for n in sub["nodes"] if UUID_RE.match(n.get("type", ""))}

    # Map outer input slot index → resolved ref (for -10 origins)
    outer_input_by_slot = {}
    for slot_idx, inp in enumerate(outer_node.get("inputs", [])):
        lid = inp.get("link")
        if lid is not None and lid in outer_lmap:
            outer_input_by_slot[slot_idx] = outer_lmap[lid]

    # For bypassed nodes: output slot i passes through input slot i.
    # Build {(bypassed_id, input_slot): (origin_id, origin_slot)}
    bypass_input = {}
    for l in inner_links:
        if l["target_id"] in bypassed_ids:
            bypass_input[(l["target_id"], l["target_slot"])] = (l["origin_id"], l["origin_slot"])

    # Partial lmap for nested UUID expansion (before nested_omaps is ready):
    # resolves -10 origins and direct regular-node refs only.
    inner_lmap_partial = {}
    for l in inner_links:
        if l["origin_id"] == -10:
            ref = outer_input_by_slot.get(l["origin_slot"])
            if ref is not None:
                inner_lmap_partial[l["id"]] = ref
        elif (l["origin_id"] not in reroute_ids and l["origin_id"] not in bypassed_ids
              and l["origin_id"] not in uuid_inner_ids and l["origin_id"] != -20):
            inner_lmap_partial[l["id"]] = [prefix + str(l["origin_id"]), l["origin_slot"]]

    # Also resolve links that pass through Reroutes to outer inputs or regular nodes.
    # These are needed so nested UUID nodes can see model/vae/clip/image routed via Reroutes.
    for l in inner_links:
        if l["id"] in inner_lmap_partial or l["origin_id"] not in reroute_ids:
            continue
        res = reroute_map.get(l["origin_id"])
        if res is None:
            continue
        rid, rslot = res
        if rid == -10:
            ref = outer_input_by_slot.get(rslot)
            if ref is not None:
                inner_lmap_partial[l["id"]] = ref
        elif (rid not in reroute_ids and rid not in bypassed_ids
              and rid not in uuid_inner_ids and rid != -20):
            inner_lmap_partial[l["id"]] = [prefix + str(rid), rslot]

    # First pass: recursively expand nested UUID subgraph nodes (mode=0 only)
    nested_omaps = {}  # {inner_node_id: output_slot_map}
    all_expanded = {}
    for n in sub["nodes"]:
        if n.get("mode", 0) != 0:
            continue
        if UUID_RE.match(n["type"]):
            nested_sub = subgraph_defs.get(n["type"])
            if not nested_sub:
                print(f"  WARNING: no subgraph def for {n['type']}, skipping", file=sys.stderr)
                continue
            n_exp, n_omap = expand_subgraph(n, nested_sub, subgraph_defs,
                                            prefix=prefix + str(n["id"]) + "_",
                                            outer_lmap=inner_lmap_partial)
            all_expanded.update(n_exp)
            nested_omaps[n["id"]] = n_omap

    def _resolve_origin(origin_id, origin_slot, depth=0):
        """Recursively resolve through Reroutes, bypassed nodes, nested UUID outputs, and -10 outer inputs."""
        if depth > 30:
            return None
        # Outer subgraph input
        if origin_id == -10:
            return outer_input_by_slot.get(origin_slot)
        # Reroute: already resolved to final non-Reroute by reroute_map
        if origin_id in reroute_ids:
            resolved = reroute_map.get(origin_id)
            if resolved is None:
                return None
            return _resolve_origin(resolved[0], resolved[1], depth + 1)
        # Bypassed: output slot i = input slot i (pass-through)
        if origin_id in bypassed_ids:
            src = bypass_input.get((origin_id, origin_slot))
            if src is None:
                return None
            return _resolve_origin(src[0], src[1], depth + 1)
        # Nested UUID subgraph
        if origin_id in nested_omaps:
            omap = nested_omaps[origin_id]
            if origin_slot in omap:
                return omap[origin_slot]
            print(f"  WARNING: nested UUID slot {origin_slot} not in omap", file=sys.stderr)
            return None
        return [prefix + str(origin_id), origin_slot]

    # Build full inner link map
    inner_lmap = {}
    for l in inner_links:
        if l["origin_id"] == -20:
            continue
        resolved = _resolve_origin(l["origin_id"], l["origin_slot"])
        if resolved is not None:
            inner_lmap[l["id"]] = resolved

    # Build output map for this subgraph
    output_map = {}
    for l in inner_links:
        if l["target_id"] == -20:
            resolved = _resolve_origin(l["origin_id"], l["origin_slot"])
            if resolved is not None:
                output_map[l["target_slot"]] = resolved

    # Second pass: expand regular (active, non-Reroute, non-UUID) nodes
    for n in sub["nodes"]:
        mode = n.get("mode", 0)
        if mode != 0 or n["type"] in UI_ONLY or n["type"] == "Reroute":
            continue
        if UUID_RE.match(n["type"]):
            continue  # already handled above
        nid = prefix + str(n["id"])
        try:
            info = obj_info(n["type"])
        except Exception:
            print(f"  WARNING: no object_info for {n['type']}, skipping", file=sys.stderr)
            continue
        inputs = resolve_node_inputs(n, info, inner_lmap)
        all_expanded[nid] = {"class_type": n["type"], "inputs": inputs}

    return all_expanded, output_map

def _is_negative(text):
    if not isinstance(text, str):
        return False
    low = text.lower()
    return any(p in low for p in ("low quality", "worst quality", "blurry", "nsfw", "watermark", "ugly", "bad anatomy"))

def inject_params(api):
    for node in api.values():
        ct = node["class_type"]
        inp = node["inputs"]
        if ct in ("CLIPTextEncode",) and "text" in inp:
            inp["text"] = "PARAM_NEGATIVE_PROMPT" if _is_negative(inp["text"]) else "PARAM_PROMPT"
        elif ct == "PrimitiveStringMultiline" and "value" in inp:
            if isinstance(inp["value"], str) and not _is_negative(inp["value"]):
                inp["value"] = "PARAM_PROMPT"
        elif ct == "TextEncodeQwenImageEditPlus" and "prompt" in inp:
            if isinstance(inp["prompt"], str) and inp["prompt"]:
                inp["prompt"] = "PARAM_PROMPT"
        if ct in ("KSampler", "KSamplerAdvanced") and "seed" in inp:
            inp["seed"] = "PARAM_INT_SEED"
        if ct == "RandomNoise" and "noise_seed" in inp:
            inp["noise_seed"] = "PARAM_INT_SEED"
        if ct == "LoadImage" and "image" in inp:
            inp["image"] = "PARAM_IMAGE"
        if ct == "LoadAudio" and "audio" in inp:
            inp["audio"] = "PARAM_AUDIO"
    return api

def convert(ui_path):
    d = json.load(open(ui_path))
    all_nodes = d["nodes"]
    outer_links = d.get("links", [])
    outer_lmap = {lk[0]: [str(lk[1]), lk[2]] for lk in outer_links}
    subgraph_defs = {s["id"]: s for s in d.get("definitions", {}).get("subgraphs", [])}

    # First pass: expand UUID nodes
    uuid_output_maps = {}  # outer_node_id -> output_slot_map
    expanded_nodes = {}
    for n in all_nodes:
        if n.get("mode", 0) != 0:
            continue
        ntype = n["type"]
        if UUID_RE.match(ntype):
            sub = subgraph_defs.get(ntype)
            if not sub:
                print(f"WARNING: no subgraph def for {ntype}", file=sys.stderr)
                continue
            cur_outer = {}
            for lid, ref in outer_lmap.items():
                fid = int(ref[0])
                fslot = ref[1]
                if fid in uuid_output_maps and fslot in uuid_output_maps[fid]:
                    cur_outer[lid] = uuid_output_maps[fid][fslot]
                else:
                    cur_outer[lid] = ref
            exp, omap = expand_subgraph(n, sub, subgraph_defs, outer_lmap=cur_outer)
            expanded_nodes.update(exp)
            uuid_output_maps[n["id"]] = omap

    # Bypassed/muted outer nodes — skip their output links so optional inputs stay absent
    bypassed_outer_ids = {n["id"] for n in all_nodes if n.get("mode", 0) != 0}

    # Second pass: convert regular outer nodes
    result = {}
    for n in all_nodes:
        if n.get("mode", 0) != 0 or n["type"] in UI_ONLY:
            continue
        ntype = n["type"]
        if UUID_RE.match(ntype):
            pfx = str(n["id"]) + "_"
            result.update({k: v for k, v in expanded_nodes.items() if k.startswith(pfx)})
            continue

        # Resolve outer links, redirecting UUID node outputs to actual inner nodes.
        # Skip links from bypassed/muted nodes — their outputs are not in result.
        resolved_lmap = {}
        for lid, (from_node_str, from_slot) in outer_lmap.items():
            from_node_id = int(from_node_str)
            if from_node_id in bypassed_outer_ids:
                continue
            if from_node_id in uuid_output_maps:
                omap = uuid_output_maps[from_node_id]
                if from_slot in omap:
                    resolved_lmap[lid] = omap[from_slot]
                else:
                    print(f"WARNING: UUID output slot {from_slot} not in omap", file=sys.stderr)
            else:
                resolved_lmap[lid] = [from_node_str, from_slot]

        try:
            info = obj_info(ntype)
        except Exception:
            print(f"WARNING: no object_info for {ntype}, skipping", file=sys.stderr)
            continue
        inputs = resolve_node_inputs(n, info, resolved_lmap)
        result[str(n["id"])] = {"class_type": ntype, "inputs": inputs}

    return inject_params(result)

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("input")
    p.add_argument("--out", default=None)
    args = p.parse_args()
    r = convert(args.input)
    out = json.dumps(r, indent=2)
    if args.out:
        open(args.out, "w").write(out)
        print(f"Written to {args.out}")
    else:
        print(out)
