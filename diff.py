import difflib

def myers_diff(a_lines, b_lines):
    """
    Classic Myers O((N+M)D) diff algorithm.
    Returns list of operations: ('equal'|'delete'|'insert', line_content)
    """
    n, m = len(a_lines), len(b_lines)
    max_d = n + m
    v = {1: 0}
    trace = []

    for d in range(max_d + 1):
        trace.append(v.copy())
        for k in range(-d, d + 1, 2):
            if k == -d or (k != d and v.get(k - 1, 0) < v.get(k + 1, 0)):
                x = v.get(k + 1, 0)
            else:
                x = v.get(k - 1, 0) + 1
            y = x - k
            while x < n and y < m and a_lines[x] == b_lines[y]:
                x += 1
                y += 1
            v[k] = x
            if x >= n and y >= m:
                return _backtrack(trace, a_lines, b_lines)
    return []

def _backtrack(trace, a, b):
    path = []
    x, y = len(a), len(b)
    for d in range(len(trace) - 1, 0, -1):
        v = trace[d]
        k = x - y
        if k == -d or (k != d and v.get(k - 1, 0) < v.get(k + 1, 0)):
            prev_k = k + 1
        else:
            prev_k = k - 1
        prev_x = v.get(prev_k, 0)
        prev_y = prev_x - prev_k
        while x > prev_x and y > prev_y:
            path.append(("equal", a[x - 1]))
            x -= 1
            y -= 1
        if d > 0:
            if x == prev_x:
                path.append(("insert", b[prev_y - 1]))
            else:
                path.append(("delete", a[prev_x]))
        x, y = prev_x, prev_y
    return list(reversed(path))

def unified_diff(old_text: str, new_text: str, old_label: str = "old", new_label: str = "new") -> str:
    """Generate human-readable unified diff."""
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=old_label,
        tofile=new_label,
        lineterm=""
    )
    return "\n".join(diff)

def three_way_merge(base_lines, ours_lines, theirs_lines):
    """
    Perform a 3-way line-based merge between base, ours, and theirs.
    Returns (merged_lines, conflict_count) tuple.
    """
    matcher_ours = difflib.SequenceMatcher(None, base_lines, ours_lines)
    matcher_theirs = difflib.SequenceMatcher(None, base_lines, theirs_lines)

    ours_opcodes = matcher_ours.get_opcodes()
    theirs_opcodes = matcher_theirs.get_opcodes()

    # Collect line-by-line changes from base for both sides
    ours_changes = {}   # base_idx -> list of lines or None (deleted)
    theirs_changes = {} # base_idx -> list of lines or None (deleted)

    def process_opcodes(opcodes, b_lines, target_lines):
        changes = {}
        for tag, i1, i2, j1, j2 in opcodes:
            if tag == 'equal':
                for idx in range(i1, i2):
                    changes[idx] = [b_lines[idx]]
            elif tag == 'replace':
                changes[i1] = target_lines[j1:j2]
                for idx in range(i1 + 1, i2):
                    changes[idx] = []
            elif tag == 'delete':
                changes[i1] = []
                for idx in range(i1 + 1, i2):
                    changes[idx] = []
            elif tag == 'insert':
                # Attach insertion before index i1
                changes.setdefault(i1, []).extend(target_lines[j1:j2])
        return changes

    ours_map = process_opcodes(ours_opcodes, base_lines, ours_lines)
    theirs_map = process_opcodes(theirs_opcodes, base_lines, theirs_lines)

    merged = []
    conflict_count = 0
    max_idx = max(len(base_lines), max(ours_map.keys(), default=0) + 1, max(theirs_map.keys(), default=0) + 1)

    for idx in range(max_idx):
        o = ours_map.get(idx, [base_lines[idx]] if idx < len(base_lines) else [])
        t = theirs_map.get(idx, [base_lines[idx]] if idx < len(base_lines) else [])
        b = [base_lines[idx]] if idx < len(base_lines) else []

        if o == t:
            merged.extend(o)
        elif o == b:
            # Only theirs changed
            merged.extend(t)
        elif t == b:
            # Only ours changed
            merged.extend(o)
        else:
            # Conflict! Both changed differently
            conflict_count += 1
            merged.append("<<<<<<< OURS")
            merged.extend(o)
            merged.append("=======")
            merged.extend(t)
            merged.append(">>>>>>> THEIRS")

    return merged, conflict_count
