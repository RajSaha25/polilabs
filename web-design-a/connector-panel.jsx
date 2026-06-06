/* global React, Icon */
// Polilabs — "Connect your agent" modal. A no-code way for a researcher
// to mint / copy / revoke the connector tokens that let their own
// approved agent (e.g. a ChatGPT Action) drive the polilabs tools.

const { useState, useEffect } = React;

function ConnectorPanel({ onClose }) {
  const [tokens, setTokens] = useState(null);   // null = loading
  const [label, setLabel] = useState("");
  const [minting, setMinting] = useState(false);
  const [fresh, setFresh] = useState(null);      // the once-shown plaintext token
  const [copied, setCopied] = useState("");
  const [error, setError] = useState("");

  const openapiUrl = window.PolilabsConnector.backendUrl() + "/openapi.json";

  const reload = () =>
    window.PolilabsConnector.list()
      .then((rows) => setTokens(rows))
      .catch((e) => { setTokens([]); setError(String(e.message || e)); });

  useEffect(() => { reload(); }, []);

  const copy = (text, key) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(key);
      setTimeout(() => setCopied(""), 1500);
    });
  };

  const mint = () => {
    setMinting(true); setError("");
    window.PolilabsConnector.mint(label.trim())
      .then((res) => { setFresh(res); setLabel(""); reload(); })
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setMinting(false));
  };

  const revoke = (jti) => {
    window.PolilabsConnector.revoke(jti).then(reload).catch((e) => setError(String(e.message || e)));
  };

  return (
    <div className="modal-scrim" onMouseDown={onClose}>
      <div className="modal connector-modal" onMouseDown={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div>
            <h2>Connect your agent</h2>
            <p className="modal-sub">
              Use your own approved AI (e.g. ChatGPT) on the polilabs corpus.
              polilabs supplies the read-only tools; you supply the model.
            </p>
          </div>
          <button className="modal-x" type="button" aria-label="Close" onClick={onClose}>
            <Icon name="x" size={16} />
          </button>
        </div>

        <div className="modal-body">
          {/* Step 1 — OpenAPI URL for ChatGPT Actions */}
          <div className="conn-step">
            <div className="conn-step-n">1</div>
            <div className="conn-step-body">
              <div className="conn-step-title">Point your agent at the tools</div>
              <p>In ChatGPT, add an Action and import this schema URL (or open it directly for any MCP client):</p>
              <div className="conn-copyrow">
                <code>{openapiUrl}</code>
                <button type="button" className="conn-copy" onClick={() => copy(openapiUrl, "url")}>
                  {copied === "url" ? "copied" : "copy"}
                </button>
              </div>
            </div>
          </div>

          {/* Step 2 — mint a token */}
          <div className="conn-step">
            <div className="conn-step-n">2</div>
            <div className="conn-step-body">
              <div className="conn-step-title">Create a connector token</div>
              <p>Paste this token into your agent's authentication (Bearer). It's shown only once.</p>
              <div className="conn-mintrow">
                <input
                  className="conn-input"
                  placeholder="Label (e.g. My ChatGPT)"
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") mint(); }}
                />
                <button type="button" className="conn-mint" onClick={mint} disabled={minting}>
                  {minting ? "creating…" : "Create token"}
                </button>
              </div>

              {fresh ? (
                <div className="conn-fresh">
                  <div className="conn-fresh-label">
                    <Icon name="check" size={12} /> Token created. Copy it now, it won't be shown again.
                  </div>
                  <div className="conn-copyrow">
                    <code className="conn-token">{fresh.token}</code>
                    <button type="button" className="conn-copy" onClick={() => copy(fresh.token, "tok")}>
                      {copied === "tok" ? "copied" : "copy"}
                    </button>
                  </div>
                </div>
              ) : null}
            </div>
          </div>

          {error ? <div className="conn-error">{error}</div> : null}

          {/* Existing tokens */}
          <div className="conn-list-head">Your connector tokens</div>
          {tokens === null ? (
            <div className="conn-empty">loading…</div>
          ) : tokens.length === 0 ? (
            <div className="conn-empty">No tokens yet.</div>
          ) : (
            <div className="conn-list">
              {tokens.map((t) => (
                <div key={t.jti} className={"conn-row" + (t.revoked ? " revoked" : "")}>
                  <div className="conn-row-main">
                    <span className="conn-row-label">{t.label || "(unlabeled)"}</span>
                    <span className="conn-row-meta mono">{t.jti.slice(0, 10)}… · {t.created_at}</span>
                  </div>
                  {t.revoked ? (
                    <span className="conn-revoked">revoked</span>
                  ) : (
                    <button type="button" className="conn-revoke" onClick={() => revoke(t.jti)}>Revoke</button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

window.ConnectorPanel = ConnectorPanel;
