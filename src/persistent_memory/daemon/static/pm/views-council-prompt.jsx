// persistent-memory — AI Council: global prompt editor + layer/config preview.
(function () {
  const React = window.React;
  const { useState, useEffect, useCallback } = React;

  const MAX_PROMPT_CHARS = 20000;
  const CONFIG_SOURCE_FILE = "file";
  const CONFIG_MEMBER_FIELDS = ["id", "backend", "model", "effort", "role", "enabled"];

  if (!document.getElementById("pm-council-prompt-css")) {
    const s = document.createElement("style");
    s.id = "pm-council-prompt-css";
    s.textContent = `
.cnp-card{padding:16px 17px;margin-top:18px}
.cnp-heading{font-size:13px;font-weight:600;color:var(--txt-hi)}
.cnp-hint{margin-top:6px;font-size:11.5px;color:var(--faint)}
.cnp-textarea{width:100%;min-height:400px;background:var(--bg2);color:var(--txt-hi);border:1px solid var(--line2);border-radius:var(--r-sm);padding:11px 12px;font-family:var(--font-mono);font-size:12.5px;line-height:1.55;resize:vertical;outline:none;margin-top:12px}
.cnp-charcount{margin-top:6px;font-family:var(--font-mono);font-size:11px;color:var(--faint);text-align:right}
.cnp-charcount.over{color:var(--st-reverted)}
.cnp-actions{display:flex;align-items:center;gap:9px;margin-top:11px}
.cnp-ok{margin-top:9px;font-size:12.5px;color:var(--st-accepted)}
.cnp-confirm{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--txt)}
.cnp-field{display:flex;flex-direction:column;gap:5px;max-width:420px}
.cnp-field .l{font-size:10.5px;text-transform:uppercase;letter-spacing:.5px;color:var(--faint)}
.cnp-layerform{display:flex;align-items:flex-end;gap:9px;flex-wrap:wrap}
.cnp-layer{margin-top:12px;border:1px solid var(--line);border-radius:var(--r-sm);padding:8px 10px}
.cnp-layer summary{cursor:pointer;display:flex;align-items:center;gap:9px;font-family:var(--font-mono);font-size:11.5px;color:var(--dim)}
.cnp-layer-src{color:var(--faint);font-size:10.5px}
.cnp-layer-pre{white-space:pre-wrap;font-family:var(--font-mono);font-size:11.5px;color:var(--txt);margin:8px 0 0;max-height:280px;overflow:auto}
.cnp-table-wrap{margin-top:12px;overflow-x:auto}
.cnp-table{border-collapse:collapse;width:100%;font-size:11.5px}
.cnp-table th,.cnp-table td{border:1px solid var(--line);padding:6px 10px;text-align:left;white-space:nowrap}
.cnp-table th{color:var(--faint);font-family:var(--font-mono);font-weight:500}
.cnp-table td{font-family:var(--font-mono);color:var(--txt)}
.cnp-meta{display:flex;gap:14px;flex-wrap:wrap;margin-top:10px;font-family:var(--font-mono);font-size:11px;color:var(--faint)}
`;
    document.head.appendChild(s);
  }

  function PromptEditor({ project }) {
    const [loading, setLoading] = useState(true);
    const [loadErr, setLoadErr] = useState(false);
    const [text, setText] = useState("");
    const [isDefault, setIsDefault] = useState(true);
    const [defaultText, setDefaultText] = useState("");
    const [version, setVersion] = useState(null);
    const [saving, setSaving] = useState(false);
    const [saveErr, setSaveErr] = useState("");
    const [saveOk, setSaveOk] = useState(false);
    const [saveConflict, setSaveConflict] = useState(false);
    const [resetConfirm, setResetConfirm] = useState(false);
    const [resetting, setResetting] = useState(false);
    const [resetErr, setResetErr] = useState("");

    const loadPrompt = useCallback(() => {
      setLoading(true);
      setLoadErr(false);
      window.PM_API.fetchCouncilPrompt().then((res) => {
        setLoading(false);
        if (!res.ok) { setLoadErr(true); return; }
        setDefaultText(res.default_text || "");
        setIsDefault(!!res.is_default);
        setText(res.is_default ? (res.default_text || "") : (res.text || ""));
        setVersion(res.version != null ? res.version : null);
      });
    }, []);

    useEffect(() => { loadPrompt(); }, [loadPrompt]);

    const overLimit = text.length > MAX_PROMPT_CHARS;

    const onSave = () => {
      if (saving || !text.trim() || overLimit) return;
      setSaving(true);
      setSaveErr("");
      setSaveOk(false);
      setSaveConflict(false);
      window.PM_API.saveCouncilPrompt(text, version).then((res) => {
        setSaving(false);
        if (!res.ok) {
          if (res.status === 409) {
            setSaveConflict(true);
            setSaveErr(res.detail || t("ui.council.prompt_conflict", "Prompt was changed elsewhere — reload before saving again."));
            return;
          }
          const detail = res.detail ? " — " + res.detail : "";
          setSaveErr(t("ui.council.prompt_save_failed", "Couldn't save prompt") + " (HTTP " + res.status + ")" + detail);
          return;
        }
        setSaveOk(true);
        setIsDefault(false);
        setVersion(res.version != null ? res.version : version);
      });
    };

    const onReloadAfterConflict = () => {
      setSaveConflict(false);
      setSaveErr("");
      loadPrompt();
    };

    const onResetYes = () => {
      if (resetting) return;
      setResetting(true);
      setResetErr("");
      window.PM_API.resetCouncilPrompt().then((res) => {
        setResetting(false);
        setResetConfirm(false);
        if (!res.ok) {
          const detail = res.detail ? " — " + res.detail : "";
          setResetErr(t("ui.council.reset_failed", "Reset failed") + " (HTTP " + res.status + ")" + detail);
          return;
        }
        setSaveOk(false);
        loadPrompt();
      });
    };

    return (
      <div className="pm-card cnp-card">
        <div className="cnp-heading">{t("ui.council.prompt_editor_heading", "Global prompt")}</div>
        {!loading && !loadErr && isDefault && (
          <div className="cnp-hint">{t("ui.council.prompt_is_default", "This is the default prompt — not yet customized.")}</div>
        )}
        {loading && <div className="pm-empty">{t("ui.cand.loading", "Loading…")}</div>}
        {!loading && loadErr && <div className="cn-err">{t("ui.council.prompt_load_error", "Couldn't load the prompt")}</div>}
        {!loading && !loadErr && (
          <React.Fragment>
            <textarea
              className="cnp-textarea"
              value={text}
              onChange={(e) => setText(e.target.value)}
              maxLength={MAX_PROMPT_CHARS}
              spellCheck={false}
            />
            <div className={"cnp-charcount" + (overLimit ? " over" : "")}>{text.length} / {MAX_PROMPT_CHARS}</div>
            <div className="cnp-actions">
              <button className="pm-btn accent" disabled={saving || !text.trim() || overLimit} onClick={onSave}>
                {t("ui.council.save_prompt", "Save")}
              </button>
              {!resetConfirm && (
                <button className="pm-btn no sm" onClick={() => setResetConfirm(true)}>
                  {t("ui.council.reset_prompt", "Reset to default")}
                </button>
              )}
              {resetConfirm && (
                <span className="cnp-confirm">
                  {t("ui.council.reset_confirm", "Reset to the default prompt?")}
                  <button className="pm-btn ok sm" disabled={resetting} onClick={onResetYes}>{t("ui.council.yes", "Yes")}</button>
                  <button className="pm-btn ghost sm" disabled={resetting} onClick={() => setResetConfirm(false)}>{t("ui.council.no", "No")}</button>
                </span>
              )}
            </div>
            {saveErr && (
              <div className="cn-err">
                {saveErr}
                {saveConflict && (
                  <button className="pm-btn no sm" style={{ marginLeft: 9 }} onClick={onReloadAfterConflict}>
                    {t("ui.council.reload_prompt", "Reload")}
                  </button>
                )}
              </div>
            )}
            {saveOk && <div className="cnp-ok">{t("ui.council.prompt_saved", "Prompt saved")}</div>}
            {resetErr && <div className="cn-err">{resetErr}</div>}
          </React.Fragment>
        )}
      </div>
    );
  }

  function LayerBlock({ layer, index }) {
    return (
      <details className="cnp-layer">
        <summary>{layer.layer} <span className="cnp-layer-src">{layer.source}</span></summary>
        <pre className="cnp-layer-pre">{layer.text}</pre>
      </details>
    );
  }

  function ConfigTable({ config, source, cwd }) {
    return (
      <div className="pm-card cnp-card">
        <div className="cnp-heading">{t("ui.council.config_heading", "Project configuration")}</div>
        <div className="cnp-hint">{t("ui.council.config_readonly_note", "Read-only — edit .pm-council.yaml in the repo to change this")}</div>
        <div className="cnp-hint">
          {source === CONFIG_SOURCE_FILE
            ? t("ui.council.config_source_file", "loaded from") + " " + cwd + "/.pm-council.yaml"
            : t("ui.council.config_source_default", "No .pm-council.yaml found — using built-in defaults")}
        </div>
        <div className="cnp-table-wrap">
          <table className="cnp-table">
            <thead>
              <tr>{CONFIG_MEMBER_FIELDS.map((f) => <th key={f}>{f}</th>)}</tr>
            </thead>
            <tbody>
              {config.members.map((m) => (
                <tr key={m.id}>
                  <td>{m.id}</td>
                  <td>{m.backend}</td>
                  <td>{m.model || "—"}</td>
                  <td>{m.effort || "—"}</td>
                  <td>{m.role || "—"}</td>
                  <td>{String(m.enabled)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="cnp-meta">
          <span>{t("ui.council.rounds", "Rounds")}: {config.rounds}</span>
          <span>{t("ui.council.turn_timeout", "turn timeout (s)")}: {config.turn_timeout_seconds}</span>
          {config.spokesperson && <span>spokesperson: {config.spokesperson}</span>}
        </div>
      </div>
    );
  }

  function LayerPreview({ project }) {
    const [cwd, setCwd] = useState("");
    const [loading, setLoading] = useState(false);
    const [err, setErr] = useState("");
    const [layers, setLayers] = useState(null);
    const [config, setConfig] = useState(null);
    const [source, setSource] = useState("");
    const [queriedCwd, setQueriedCwd] = useState("");

    const onShowLayers = () => {
      if (!project || !cwd.trim() || loading) return;
      setLoading(true);
      setErr("");
      window.PM_API.fetchCouncilConfig(project, cwd.trim()).then((res) => {
        setLoading(false);
        if (!res.ok) {
          const detail = res.detail ? " — " + res.detail : "";
          setErr(t("ui.council.layers_error", "Couldn't load layers") + " (HTTP " + res.status + ")" + detail);
          setLayers(null);
          setConfig(null);
          return;
        }
        setLayers(res.prompt_layers || []);
        setConfig(res.config || null);
        setSource(res.source || "");
        setQueriedCwd(cwd.trim());
      });
    };

    return (
      <React.Fragment>
        <div className="pm-card cnp-card">
          <div className="cnp-heading">{t("ui.council.layer_preview_heading", "Active layers")}</div>
          <div className="cnp-hint">{t("ui.council.layer_preview_hint", "See which prompt layers apply for a given project directory")}</div>
          <div className="cnp-layerform" style={{ marginTop: 12 }}>
            <label className="cnp-field">
              <span className="l">{t("ui.council.cwd", "Working directory")}</span>
              <input
                className="cn-forminput"
                value={cwd}
                onChange={(e) => setCwd(e.target.value)}
                placeholder={t("ui.council.cwd_placeholder", "/absolute/path/to/project")}
              />
            </label>
            <button className="pm-btn" disabled={!project || !cwd.trim() || loading} onClick={onShowLayers}>
              {t("ui.council.show_layers", "Show layers")}
            </button>
          </div>
          {err && <div className="cn-err">{err}</div>}
          {layers && layers.map((layer, i) => <LayerBlock key={layer.layer + "-" + i} layer={layer} index={i} />)}
        </div>
        {config && <ConfigTable config={config} source={source} cwd={queriedCwd} />}
      </React.Fragment>
    );
  }

  function CouncilPrompt({ project }) {
    return (
      <div>
        <PromptEditor project={project} />
        <LayerPreview project={project} />
      </div>
    );
  }

  window.PMCouncilPrompt = CouncilPrompt;
})();
