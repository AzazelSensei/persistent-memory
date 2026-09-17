// persistent-memory — Agent rules & memory view: browse and edit every
// Claude / Codex / Grok rule and memory file the daemon can see, from one
// screen. Left: agent -> layer -> scope tree built from the inventory
// groups. Right: the selected file, rendered read-only or as a textarea.
(function () {
  const React = window.React;
  const { useState, useEffect, useMemo } = React;
  const { Icon } = window.PMUI;

  if (!document.getElementById("pm-agents-css")) {
    const s = document.createElement("style");
    s.id = "pm-agents-css";
    s.textContent = `
.ag-wrap{display:flex;gap:0;align-items:flex-start}
.ag-tree{width:300px;flex:0 0 300px;border-right:1px solid var(--line);padding-right:16px;
  overflow-y:auto;max-height:calc(100vh - 210px)}
.ag-main{flex:1;min-width:0;padding-left:24px}
.ag-agent{margin-bottom:8px}
.ag-agent-h{display:flex;align-items:center;gap:8px;padding:8px 6px;font-size:12.5px;font-weight:600;
  color:var(--txt-hi);text-transform:uppercase;letter-spacing:.5px}
.ag-layer{margin-left:9px}
.ag-layer-h{font-size:11px;text-transform:uppercase;letter-spacing:.6px;color:var(--faint);padding:6px 6px 2px}
.ag-scope{margin-left:6px}
.ag-row{display:flex;align-items:center;gap:7px;padding:6px 8px;border-radius:var(--r-sm);cursor:pointer;
  font-size:13px;color:var(--dim)}
.ag-row:hover{background:var(--panel-hi);color:var(--txt)}
.ag-row.on{background:var(--accent-soft);color:var(--accent-ink)}
.ag-row .n{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ag-row .c{font-family:var(--font-mono);font-size:10.5px;color:var(--faint)}
.ag-file{margin-left:17px}
.ag-head{display:flex;align-items:center;gap:12px;margin-bottom:16px}
.ag-head .id{font-family:var(--font-mono);font-size:12px;color:var(--faint)}
.ag-head .sp{flex:1}
.ag-view{font-size:13.5px;line-height:1.65;color:var(--txt)}
.ag-editor{width:100%;min-height:460px;background:var(--bg2);color:var(--txt-hi);border:1px solid var(--line2);
  border-radius:var(--r-sm);padding:12px;font-family:var(--font-mono);font-size:12.5px;line-height:1.6;
  resize:vertical;outline:none}
.ag-acts{display:flex;gap:9px;margin-top:12px;align-items:center}
.ag-confirm{display:flex;align-items:center;gap:10px;padding:10px 14px;border-radius:var(--r-sm);
  background:color-mix(in srgb,var(--st-proposed) 12%,var(--panel));
  border:1px solid color-mix(in srgb,var(--st-proposed) 35%,var(--line2));margin-bottom:14px;font-size:12.5px}
.ag-confirm .sp{flex:1}
`;
    document.head.appendChild(s);
  }

  function groupKey(agent, layer, scope) {
    return agent + ":" + layer + ":" + scope;
  }

  function buildTree(groups) {
    const tree = [];
    const byAgent = {};
    groups.forEach((g) => {
      let agentNode = byAgent[g.agent];
      if (!agentNode) {
        agentNode = { agent: g.agent, layers: {}, layerOrder: [] };
        byAgent[g.agent] = agentNode;
        tree.push(agentNode);
      }
      if (!agentNode.layers[g.layer]) {
        agentNode.layers[g.layer] = [];
        agentNode.layerOrder.push(g.layer);
      }
      agentNode.layers[g.layer].push(g);
    });
    return tree;
  }

  function ScopeNode({ group, assets, selectedId, expanded, onToggle, onSelect }) {
    const key = groupKey(group.agent, group.layer, group.scope);
    const isMulti = group.count > 1;
    const isOpen = !!expanded[key];
    const onlyAsset = assets[0];
    const rowLabel = isMulti ? group.scope : (onlyAsset ? onlyAsset.name : group.scope);
    const isSelected = !isMulti && !!onlyAsset && selectedId === onlyAsset.id;

    const onRowClick = () => {
      if (isMulti) onToggle(key);
      else if (onlyAsset) onSelect(onlyAsset.id);
    };

    return (
      <div className="ag-scope">
        <div className={"ag-row" + (isSelected ? " on" : "")} onClick={onRowClick}>
          <Icon name="chevR" size={12} style={{ opacity: isMulti ? 1 : 0, transform: isOpen ? "rotate(90deg)" : "none" }} />
          <span className="n">{rowLabel}</span>
          {isMulti && <span className="c">{group.count}</span>}
        </div>
        {isMulti && isOpen && assets.map((a) => (
          <div key={a.id} className={"ag-row ag-file" + (selectedId === a.id ? " on" : "")} onClick={() => onSelect(a.id)}>
            <span className="n">{a.name}</span>
          </div>
        ))}
      </div>
    );
  }

  function LayerNode({ layer, groups, assetsByGroup, selectedId, expanded, onToggle, onSelect }) {
    return (
      <div className="ag-layer">
        <div className="ag-layer-h">{layer}</div>
        {groups.map((g) => (
          <ScopeNode key={groupKey(g.agent, g.layer, g.scope)} group={g}
            assets={assetsByGroup[groupKey(g.agent, g.layer, g.scope)] || []}
            selectedId={selectedId} expanded={expanded} onToggle={onToggle} onSelect={onSelect} />
        ))}
      </div>
    );
  }

  function AssetTree({ tree, assetsByGroup, selectedId, expanded, onToggle, onSelect }) {
    return (
      <div className="ag-tree">
        {tree.map((node) => (
          <div className="ag-agent" key={node.agent}>
            <div className="ag-agent-h"><Icon name="project" size={14} />{node.agent}</div>
            {node.layerOrder.map((layer) => (
              <LayerNode key={layer} layer={layer} groups={node.layers[layer]}
                assetsByGroup={assetsByGroup} selectedId={selectedId} expanded={expanded}
                onToggle={onToggle} onSelect={onSelect} />
            ))}
          </div>
        ))}
      </div>
    );
  }

  function AgentsView({ nav }) {
    const [inventory, setInventory] = useState(null);
    const [selectedId, setSelectedId] = useState(null);
    const [expanded, setExpanded] = useState({});
    const [content, setContent] = useState("");
    const [draft, setDraft] = useState("");
    const [editing, setEditing] = useState(false);
    const [saveMsg, setSaveMsg] = useState("");
    const [saveErr, setSaveErr] = useState("");
    const [pendingId, setPendingId] = useState(null);

    useEffect(() => {
      let alive = true;
      window.PM_API.fetchAgentAssets().then((data) => { if (alive) setInventory(data); });
      return () => { alive = false; };
    }, []);

    useEffect(() => {
      if (!selectedId) { setContent(""); setDraft(""); setEditing(false); return undefined; }
      let alive = true;
      setEditing(false);
      setSaveMsg("");
      setSaveErr("");
      window.PM_API.fetchAgentAssetRaw(selectedId).then((d) => {
        if (!alive) return;
        if (d && typeof d.content === "string") {
          setContent(d.content);
          setDraft(d.content);
        } else {
          setContent("");
          setDraft("");
        }
      });
      return () => { alive = false; };
    }, [selectedId]);

    const dirty = editing && draft !== content;

    const onToggle = (key) => setExpanded((e) => ({ ...e, [key]: !e[key] }));

    const doSelect = (id) => { setSelectedId(id); setPendingId(null); };
    const trySelect = (id) => {
      if (id === selectedId) return;
      if (dirty) { setPendingId(id); return; }
      doSelect(id);
    };
    const confirmDiscard = () => doSelect(pendingId);
    const cancelDiscard = () => setPendingId(null);

    const startEdit = () => { setDraft(content); setEditing(true); setSaveMsg(""); setSaveErr(""); };
    const cancelEdit = () => { setDraft(content); setEditing(false); setSaveErr(""); };
    const saveEdit = () => {
      setSaveErr("");
      window.PM_API.saveAgentAsset(selectedId, draft).then((res) => {
        if (res.ok) {
          setContent(draft);
          setEditing(false);
          setSaveMsg(t("ui.agents.saved", "Saved"));
          window.PM_API.fetchAgentAssets().then((data) => setInventory(data));
        } else {
          setSaveErr("Save failed (HTTP " + res.status + ")");
        }
      });
    };

    const assets = (inventory && inventory.assets) || [];
    const groups = (inventory && inventory.groups) || [];
    const assetsByGroup = useMemo(() => {
      const map = {};
      assets.forEach((a) => {
        const key = groupKey(a.agent, a.layer, a.scope);
        (map[key] = map[key] || []).push(a);
      });
      return map;
    }, [assets]);
    const tree = useMemo(() => buildTree(groups), [groups]);
    const selectedAsset = assets.find((a) => a.id === selectedId) || null;

    return (
      <div className="pm-page fade-in">
        <div className="pm-eyebrow">Claude · Codex · Grok</div>
        <h1 className="pm-h" style={{ marginTop: 6 }}>{t("ui.agents.heading", "Agent rules & memory")}</h1>
        <div className="ag-wrap" style={{ marginTop: 20 }}>
          {inventory === null ? (
            <div className="ag-tree pm-empty">Loading…</div>
          ) : (
            <AssetTree tree={tree} assetsByGroup={assetsByGroup} selectedId={selectedId}
              expanded={expanded} onToggle={onToggle} onSelect={trySelect} />
          )}
          <div className="ag-main">
            {pendingId && (
              <div className="ag-confirm">
                <span>{t("ui.agents.unsaved_warning", "You have unsaved changes. Discard them?")}</span>
                <span className="sp" />
                <button className="pm-btn no sm" onClick={confirmDiscard}>{t("ui.council.yes", "Yes")}</button>
                <button className="pm-btn ghost sm" onClick={cancelDiscard}>{t("ui.council.no", "No")}</button>
              </div>
            )}
            {!selectedAsset ? (
              <div className="pm-empty">{t("ui.agents.empty", "Select a file from the left.")}</div>
            ) : (
              <div>
                <div className="ag-head">
                  <span className="id">{selectedAsset.id}</span>
                  <span className="sp" />
                  {!editing && (
                    <button className="pm-btn ghost sm" onClick={startEdit}>
                      <Icon name="edit" size={14} /> {t("ui.agents.edit", "Edit")}
                    </button>
                  )}
                </div>
                {editing ? (
                  <div>
                    <textarea className="ag-editor" value={draft} spellCheck={false}
                      onChange={(e) => setDraft(e.target.value)} />
                    <div className="ag-acts">
                      <button className="pm-btn accent" onClick={saveEdit}>{t("ui.agents.save", "Save")}</button>
                      <button className="pm-btn ghost" onClick={cancelEdit}>Cancel</button>
                      {saveMsg && <span style={{ color: "var(--st-accepted)", fontSize: 12.5 }}>{saveMsg}</span>}
                      {saveErr && <span style={{ color: "var(--st-reverted)", fontSize: 12.5 }}>{saveErr}</span>}
                    </div>
                  </div>
                ) : (
                  <div className="ag-view">{window.PMMarkdown.renderMarkdown(content, { nav })}</div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  window.PMAgents = AgentsView;
})();
