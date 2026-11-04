# SECURITY_AUDIT.md — focused review

Method: `cloudflare/security-audit-skill` (cloned read-only to `vendor/`). The brief named four focus areas, so the skill ran in **guidance mode** (focused review) rather than the full six-phase multi-agent audit. Its core principles were applied: each finding needs a trust boundary and a concrete result, priority is kept separate from certainty, and every finding gets the smallest effective source fix. No target code was run against external services. The UI was only exercised on loopback in the Playwright smoke test.

Date: 2026-11-04. Scope: secrets handling, broker adapters, `x_publisher.py` and social posting, Docker setup, plus the Streamlit UI where it touches secrets.

## Coverage ledger

| Area | Files reviewed | Result |
|---|---|---|
| Secrets at rest | `core/state_manager.py`, `.gitignore`, `.env.example`, `config/settings.json` path | S2, S3 fixed |
| Secrets in transit to the browser | `app.py` sidebar | S1 fixed, regression test added |
| Secrets in git | whole tree, history not rewritten | Clean (`scripts/check_no_secrets.py --all`). Guard added to CI and the pre-commit hook |
| Broker adapters | `broker_client.py` `IBKRClient`, `KabuStationClient`, `PaperTradingEngine` | S4 fixed |
| Social / outbound posting | `x_publisher.py`, `core/x_publisher.py`, `hedge_fund_notifier.py`, `fund_content_generator.py`, UI Discord button | S5 fixed |
| Docker | `Dockerfile`, `docker-compose.yml` | S6, S7, S8 fixed |
| HTML injection | `ui/mode_ai_hedge_fund.py` (83 `unsafe_allow_html` sites) | S9: council dialogue and thesis fixed. The rest is residual |
| Subprocess | `rust_sentinel_bridge.py` (fixed argv, no shell) | No finding |
| Deserialisation / eval | none found (`grep eval/exec/pickle/yaml.load/shell=True`) | No finding |

## Findings

| ID | Priority | Certainty | Boundary → result | Fix |
|---|---|---|---|---|
| S1 | **P0** | Confirmed (test failed before the fix) | Server env → browser. `app.py` pre-filled `GEMINI_API_KEY`/`OPENAI_API_KEY` into password inputs. The value reaches every client of the dashboard, so anyone who can open the page (e.g. Docker previously published port 8501 on 0.0.0.0) can read the key from the DOM. | Inputs start empty, blank means use the server-side key. `tests/test_ui_smoke.py` asserts a canary key never appears in the page HTML or input values. |
| S2 | P1 | Confirmed | Local user → credentials. `save_app_settings` wrote API keys, X tokens and the note.com password to `config/settings.json` with default umask (often 0644). | The file is now created 0600. It was already git-ignored. |
| S3 | P1 | Confirmed | Repo → Neo4j. A hard-coded default password `LuminaAI_2026_Secure` appeared in compose, `.env.example`, the Graphiti manager, the README and the UI hint. | Compose now requires `NEO4J_PASSWORD` from env. No code default. Docs use `$NEO4J_PASSWORD`. |
| S4 | **P0** (policy) | Confirmed | Research app → real broker. `IBKRClient.place_order` routes real orders when a gateway is reachable. Kabu `authenticate` sends the API password. | Both refuse unless `LUMINA_ALLOW_LIVE_BROKER=1`, which this fork never sets. Tested. |
| S5 | **P0** (policy) | Confirmed | App → public social accounts. `XPublisher.post_tweet` (called from the UI) and the Discord bot/webhook posted whenever credentials existed. | Both are hard-disabled unless `LUMINA_ENABLE_SOCIAL_POSTING=1` (never set). The UI shows a preview-only warning. Tested. |
| S6 | P1 | Confirmed | Network → dashboard and DB. Compose published 8501, 7474 and 7687 on all interfaces. | Ports are bound to `127.0.0.1`. |
| S7 | P2 | Confirmed | Container → host. The image ran as root. | Non-root `lumina` user (uid 10001) and `LUMINA_DATA_DIR` in the user's home. |
| S8 | P2 | Confirmed | Supply chain. `neo4j:latest` and unpinned pip versions. | Pinned to `neo4j:5.26` and an exact `requirements.txt`. |
| S9 | P1 | Plausible (not exploited) | News/LLM text → browser. Headlines are fed into LLM prompts, and the resulting `dialogue`/`thesis` was rendered with `unsafe_allow_html=True`. A crafted headline could inject markup (e.g. `<img onerror>`). | `html.escape` on the agent name, title, stance, dialogue and screener thesis. **Residual:** about 80 other `unsafe_allow_html` sites interpolate mostly internal values. Each needs a review (see HANDOFF). |
| S10 | P2 | Confirmed | Stale idempotency reservation (`place_order` early returns) could block legitimate orders. This is availability, not confidentiality. | Reservations are now released on every rejection path. Tested. |

## Not verified
- Live behaviour of the IBKR and Kabu gateways was not exercised, deliberately (hard rule 1).
- Git history was not scanned for secrets that were committed and later removed. Recommended: `gitleaks detect` with full history, outside this session.
- Third-party packages were not audited.
