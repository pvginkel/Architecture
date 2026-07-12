#!/usr/bin/env python3
"""Generate per-repo seed prompts for the architecture backfill.

Encodes the locked modeling conventions (see docs/backfill/decisions.md) once,
then renders one prompt per producer from the PRODUCERS table. Writes
docs/backfill/prompts/<producer>.md. GitblitMCPServer (two producers in one repo)
is hand-authored separately, not here.
"""

from pathlib import Path

OUT = Path(__file__).resolve().parent / "prompts"

CONVENTIONS = """\
# Locked modeling conventions (apply exactly; do not re-litigate)

- **Mode: hand-authored.** The YAML is the source of truth. Mint a uuid4 per
  element with `python3 -c 'import uuid; print(uuid.uuid4())'`; never re-mint.
- **`introduced` date = this repo's FIRST commit**, the SAME date on every
  element. Get it with: `git log --reverse --format=%ad --date=short | head -1`.
- **Survey for outbound dependencies** with `grep -rIi '://'` (triage out docs,
  examples, schema/namespace URLs) AND an env-var/config scan. Real dependencies
  often live as hardcoded base-URL constants in code, invisible to an env scan.
- **External SaaS you actually call → an `ApplicationService` `svc:` element**
  you declare here (e.g. `svc:openai-api`, `svc:mouser-api`): set
  `stats: {{homepage: "<url>"}}`, NO «SoftwareProduct», and add
  `<this-app> —Association→ svc:<ext>`. Include `boundBy: "env:<VAR>"` ONLY if an
  env var carries the endpoint; when the base URL is hardcoded (the common case),
  omit boundBy. A URL-rewriter / helper that is not an API you call is OUT.
  Do NOT invent a capability to hang an external dependency on.
- **Substitutable in-house infra → a curated `cap:` target** with REQUIRED
  `boundBy: "env:<VAR>"`: OIDC/IdP → `cap:iam` (env carries issuer URL), SQL →
  `cap:relational-database`, S3/object store → `cap:object-storage`, etc. Use the
  capability enum in the manual; never mint a new capability.
- **In-house provider services (e.g. the SSE gateway) → reference the provider's
  specific `svc:<uuid>`** (not a capability). The SSE-gateway webhook the app
  exposes is an IMPLEMENTATION DETAIL of consuming the gateway — model ONE edge
  `<this-app> —Association→ svc:<ssegateway-...> boundBy env:<gateway URL var>`,
  not a second interface on this app.
- **Operational surfaces are OUT**: `/metrics` (Prometheus), drain/preStop
  endpoints — they belong to the deployment (helm-charts) lens, not the app.
- **Exposed API**: model ONE `ApplicationService` realized by the product
  (`app —Realization→ svc`), with ONE `ApplicationInterface` per DISTINCT consumer
  class (`if —Assignment→ svc`) — group by consumer, never per route. Most apps
  have a single consumer (their UI/SPA).
- **App→app edges**: model frontend→backend (a UI consuming its backend API).
  Do NOT model trivial backend→frontend calls (e.g. a version-check ping).
- `environment`/`cluster` stay UNSET on these logical, type-level surfaces (they
  span every deployed env; per-env placement is the helm-charts producer's job).
- Cross-producer ids resolve from the published dataset
  `https://architecture.webathome.org/data/v0.1/architecture.yaml` (fetch + look
  up hint+kind → uuid). A reference to a not-yet-published producer may dangle —
  the validator reports, doesn't fail it; note it in SEED-NOTES.

# Deliverables (write into the working tree; do NOT git commit, push, or branch)

1. `{arch_dir}/architecture.yaml` — `producer: {producer}`. The product(s), the
   exposed service+interface(s), capability realizations (only if it genuinely
   provides one — most realize none), and the outbound consumption edges above.
2. `scripts/arch-validate.py` — copy from the `arch` plugin's `scripts/arch-validate.py`, `chmod +x`.
3. Validate until clean: `./scripts/arch-validate.py {validate_glob}` must exit 0
   (cross-producer dangling refs are acceptable and reported, not failing).
4. `{jenkinsfile}` at {jenkinsfile_loc} — EXACTLY this house style:

   ```groovy
   // Architecture producer pipeline for the federated Architecture-as-Code model.
   // Source of truth: the hand-authored {arch_dir}/*.yaml in this repo.
   // The agent needs outbound HTTPS to architecture.webathome.org for validation.

   library('JenkinsPipelineUtils') _

   podTemplate(inheritFrom: 'jenkins-agent', containers: [
       containerTemplates.python('python')
   ]) {{
       node(POD_LABEL) {{
           stage('Cloning repo') {{
               git branch: 'main',
                   credentialsId: '5f6fbd66-b41c-405f-b107-85ba6fd97f10',
                   url: '{clone_url}'
           }}

           stage('Architecture') {{
               container('python') {{
                   sh './scripts/arch-validate.py {validate_glob}'
               }}
               archiveArtifacts artifacts: '{validate_glob}', fingerprint: true
           }}
       }}
   }}
   ```

5. Append the block from the `arch` plugin's `assets/claude-md-snippet.md` to this
   repo's `CLAUDE.md` (it may be a symlink to `AGENTS.md` — appending follows the
   link, which is fine), replacing `<ARCH-PATH>` with `{arch_dir}/architecture.yaml`.
6. `{arch_dir}/SEED-NOTES.md` — every non-trivial decision: included/excluded and
   why, each minted id, every boundBy env var + target, every external `svc:` and
   its homepage, every cross-producer reference (resolved uuid or noted dangling),
   and every open question you'd have asked a human.

# Constraints
- No commits, pushes, or branch changes. No defensive padding; fail loudly.
  Empty section → omit it. Do not read secret VALUES (env var names / config keys
  are fine).

# Final message
Return a concise summary: element inventory (ids + labels), relations, validation
exit status, and the bulleted open questions from SEED-NOTES.
"""

HEADER = """\
You are seeding the FIRST architecture artifact for this repository as a producer
in the webathome.org federated Architecture-as-Code system. You are running
HEADLESS — no human is available mid-run, so make best-effort modeling decisions
and log assumptions/uncertainties in SEED-NOTES rather than blocking.

# Read first
1. The `arch` plugin's `references/producer-manual.md` — authoritative vocabulary, ID
   grammar, element kinds, inclusion rule, relations/triple matrix, boundBy.
2. This repo's `CLAUDE.md`/`AGENTS.md`, `README.md`, `docs/`.

Then run the `/arch:seed-architecture` skill's method (survey via parallel Explore
agents → author → validate). Use the Skill tool to load it. SKIP its interactive
triage step — decide yourself and log to SEED-NOTES. Default borderline elements
to `out` per the inclusion rule.

# Fixed facts for THIS repo (do not re-derive identity)
- Producer id (envelope `producer:` key): `{producer}`
{products_block}
{role_block}{special_block}{deps_block}
"""


def render(p: dict) -> str:
    products = "\n".join(
        f"- Owns «SoftwareProduct» ApplicationComponent `{pr['id']}` "
        f"(composite id, freshly minted uuid4, `stereotype: SoftwareProduct`, "
        f"`sourceRepository: {pr['source_repo']}`). Image `registry:5000/{pr['image']}`."
        for pr in p["products"]
    )
    role_block = f"- Role: {p['role']}\n" if p.get("role") else ""
    special_block = f"- NOTE: {p['special']}\n" if p.get("special") else ""
    deps_block = ""
    if p.get("deps_hint"):
        deps_block = ("- Known/likely outbound dependencies to verify and model "
                      "(confirm via survey; this is a hint, not a closed list): "
                      f"{p['deps_hint']}\n")
    if p.get("consumes_ssegateway"):
        deps_block += (
            "- The in-house SSE gateway is already seeded; reference its service by "
            f"this exact UUID: `{SSEGATEWAY_SVC}`. IF this app consumes the gateway "
            "(look for a gateway URL / CALLBACK_URL in config), add "
            f"`<this-app> —Association→ {SSEGATEWAY_SVC}` with `boundBy: \"env:<the "
            "gateway-URL var>\"`. (It is not in the published dataset yet, so use this "
            "hand-provided UUID rather than resolving it.)\n")
    arch_dir = p.get("arch_dir", "docs/architecture")
    body = HEADER.format(
        producer=p["producer"],
        products_block=products,
        role_block=role_block,
        special_block=special_block,
        deps_block=deps_block,
    )
    conv = CONVENTIONS.format(
        producer=p["producer"],
        arch_dir=arch_dir,
        validate_glob=f"{arch_dir}/*.yaml",
        jenkinsfile=p.get("jenkinsfile", "Jenkinsfile.architecture"),
        jenkinsfile_loc=p.get("jenkinsfile_loc", "repo root"),
        clone_url=p["clone_url"],
    )
    return body + "\n" + conv


# Resolved during the Phase A run (ssegateway seed). Hand-injected into consumers
# because ssegateway isn't published to the dataset yet.
SSEGATEWAY_SVC = "svc:ssegateway,59a7d043-bb0c-4e44-a8b8-3e943338f807"

SSE_SVC = ("This is an IN-HOUSE PROVIDER other apps consume. Model the service it "
           "exposes (its SSE publish/send API) as a `svc:` ApplicationService with an "
           "interface — backends will reference this service's UUID. Get the modeling "
           "right; it is a dependency target for many producers.")

PRODUCERS = [
    # ---- Phase A: shared provider ----
    {"producer": "ssegateway", "phase": "A", "clone_dir": "SSEGateway",
     "clone_url": "https://github.com/pvginkel/SSEGateway.git",
     "products": [{"id": "app:ssegateway", "image": "ssegateway", "source_repo": "git:pvginkel/SSEGateway"}],
     "role": SSE_SVC},

    # ---- Phase B: backends + standalone apps ----
    {"consumes_ssegateway": True, "producer": "electronics-inventory", "phase": "B", "clone_dir": "ElectronicsInventory",
     "clone_url": "https://github.com/pvginkel/ElectronicsInventory.git",
     "products": [{"id": "app:electronics-inventory", "image": "electronics-inventory", "source_repo": "git:pvginkel/ElectronicsInventory"}],
     "role": "Flask backend (BFF) for the electronics parts inventory; backend only (the UI is a separate producer).",
     "deps_hint": "OIDC→cap:iam, Postgres→cap:relational-database, S3/Ceph→cap:object-storage, the SSE gateway (svc), and external SaaS svc:openai-api, svc:mouser-api, and the Google favicon service (https://www.google.com/s2/favicons)."},
    {"consumes_ssegateway": True, "producer": "iotsupport-app", "phase": "B", "clone_dir": "IoTSupport",
     "clone_url": "https://github.com/pvginkel/IoTSupport.git",
     "products": [{"id": "app:iotsupport-app", "image": "iotsupport-app", "source_repo": "git:pvginkel/IoTSupport"}],
     "role": "Backend for IoT support; backend only (UI is a separate producer)."},
    {"consumes_ssegateway": True, "producer": "dhcpapp", "phase": "B", "clone_dir": "DHCPApp",
     "clone_url": "https://github.com/pvginkel/DHCPApp.git",
     "products": [{"id": "app:dhcpapp", "image": "dhcpapp", "source_repo": "git:pvginkel/DHCPApp"}],
     "role": "Backend for the DHCP management app; backend only (UI is a separate producer)."},
    {"consumes_ssegateway": True, "producer": "zigbee-control", "phase": "B", "clone_dir": "ZigbeeControl",
     "clone_url": "https://github.com/pvginkel/ZigbeeControl.git",
     "products": [{"id": "app:zigbee-control", "image": "zigbee-control", "source_repo": "git:pvginkel/ZigbeeControl"}],
     "role": "Backend for Zigbee device control; backend only (UI is a separate producer)."},
    {"consumes_ssegateway": True, "producer": "design-assistant", "phase": "B", "clone_dir": "DesignAssistant",
     "clone_url": "https://github.com/pvginkel/DesignAssistant.git",
     "products": [
         {"id": "app:design-assistant", "image": "design-assistant", "source_repo": "git:pvginkel/DesignAssistant"},
         {"id": "app:design-assistant-frontend", "image": "design-assistant-frontend", "source_repo": "git:pvginkel/DesignAssistant"},
         {"id": "app:design-assistant-portal", "image": "design-assistant-portal", "source_repo": "git:pvginkel/DesignAssistant"},
         {"id": "app:design-assistant-manuals", "image": "design-assistant-manuals", "source_repo": "git:pvginkel/DesignAssistant"},
         {"id": "app:design-assistant-canon-docs", "image": "design-assistant-canon-docs", "source_repo": "git:pvginkel/DesignAssistant"},
     ],
     "role": "MONOREPO building 5 in-house products (above), all in ONE architecture.yaml. Model each product, the API service(s) the backend exposes, and the intra-product frontend→backend edges. The `document-conversion` image is owned by the DockerImages producer — reference if needed, do NOT declare it.",
     "special": "Jenkinsfile.architecture goes in the repo ROOT (one root Jenkinsfile, per the operator)."},
    {"producer": "ginbov-nl", "phase": "B", "clone_dir": "Ginbov",
     "clone_url": "https://github.com/pvginkel/Ginbov.git",
     "products": [{"id": "app:ginbov-nl", "image": "ginbov_nl", "source_repo": "git:pvginkel/Ginbov"}],
     "role": "Standalone app/site."},
    {"producer": "newsfilter", "phase": "B", "clone_dir": "NewsFilter",
     "clone_url": "https://github.com/pvginkel/NewsFilter.git",
     "products": [{"id": "app:newsfilter", "image": "newsfilter", "source_repo": "git:pvginkel/NewsFilter"}],
     "role": "Standalone app."},
    {"producer": "scantopdf-server", "phase": "B", "clone_dir": "ScanToPdf",
     "clone_url": "https://github.com/pvginkel/ScanToPdf.git",
     "products": [{"id": "app:scantopdf-server", "image": "scantopdf-server", "source_repo": "git:pvginkel/ScanToPdf"}],
     "role": "Standalone scan-to-PDF server."},
    {"producer": "webathome-org", "phase": "B", "clone_dir": "Webathome",
     "clone_url": "https://github.com/pvginkel/Webathome.git",
     "products": [{"id": "app:webathome-org", "image": "webathome_org", "source_repo": "git:pvginkel/Webathome"}],
     "role": "The webathome.org public website (Astro). Standalone."},
    {"producer": "mydownloads", "phase": "B", "clone_dir": "MyDownloads",
     "clone_url": "https://github.com/pvginkel/MyDownloads.git",
     "products": [{"id": "app:mydownloads", "image": "mydownloads", "source_repo": "git:pvginkel/MyDownloads"}],
     "role": "The deployed mydownloads image is built here.",
     "special": "PACKAGING repo: its Jenkinsfile bundles copyArtifacts from MyDownloadsServer (the real server source) + MyDownloadsClient (Android APK) into one image. Model the LOGICAL app product `app:mydownloads` and its real runtime dependencies (survey what the server actually talks to). sourceRepository stays git:pvginkel/MyDownloads (the deployed-image repo)."},

    {"producer": "gitblit-mcp-server", "phase": "B", "clone_dir": "GitblitMCPServer",
     "clone_url": "https://github.com/pvginkel/GitblitMCPServer.git",
     "products": [{"id": "app:gitblit-mcp-server", "image": "gitblit-mcp-server", "source_repo": "git:pvginkel/GitblitMCPServer"}],
     "role": "An MCP (Model Context Protocol) server giving AI assistants read access to Gitblit-hosted Git repos. Standard single-app repo (the old plugin/+server/ monorepo split no longer exists at HEAD).",
     "deps_hint": "Gitblit (the in-house Git host) for source-control/repo read access → likely cap:source-control with boundBy on the gitblit base-URL env var; verify via survey."},

    {"producer": "gitblit-initializer", "phase": "A2", "clone_dir": "GitblitMCPSupportPlugin",
     "clone_url": "https://github.com/pvginkel/GitblitMCPSupportPlugin.git",
     "products": [{"id": "app:gitblit-initializer", "image": "gitblit-initializer", "source_repo": "git:pvginkel/GitblitMCPSupportPlugin"}],
     "role": "A Gitblit plugin (Java/Maven) that adds REST API endpoints to Gitblit for the Gitblit MCP Server integration. It runs inside Gitblit and exposes a REST surface consumed by the gitblit-mcp-server. Model the product and the REST service/interface it exposes; if it consumes Gitblit's own platform, model that honestly.",
     "special": "The image name is misleading: this 'initializer' is the support plugin. Note in SEED-NOTES any cross-producer relationship to app:gitblit-mcp-server (already seeded, in ../GitblitMCPServer)."},

    # ---- Phase C: UIs (reference their backend's svc UUID from the Phase-B artifact) ----
    {"producer": "electronics-inventory-ui", "phase": "C", "clone_dir": "ElectronicsInventoryUI",
     "clone_url": "https://github.com/pvginkel/ElectronicsInventoryUI.git",
     "products": [{"id": "app:electronics-inventory-ui", "image": "electronics-inventory-ui", "source_repo": "git:pvginkel/ElectronicsInventoryUI"}],
     "role": "The web UI (SPA) for Electronics Inventory.",
     "special": "Author the frontend→backend edge: read the backend producer's artifact at `../ElectronicsInventory/docs/architecture/architecture.yaml`, find its ApplicationService `svc:electronics-inventory-api,<uuid>`, and add `app:electronics-inventory-ui —Association→ svc:<that-uuid>` (boundBy the env var carrying the API base URL if one exists). Also model OIDC/iam if the SPA authenticates directly. The `electronics-inventory-docs` image built here is not a deployed app:* product — do not declare it."},
    {"producer": "iotsupport-ui", "phase": "C", "clone_dir": "IoTSupportUI",
     "clone_url": "https://github.com/pvginkel/IoTSupportUI.git",
     "products": [{"id": "app:iotsupport-ui", "image": "iotsupport-ui", "source_repo": "git:pvginkel/IoTSupportUI"}],
     "role": "The web UI for IoT support.",
     "special": "Frontend→backend edge: read `../IoTSupport/docs/architecture/architecture.yaml`, find its ApplicationService (svc:…-api,<uuid>), and add `app:iotsupport-ui —Association→ svc:<that-uuid>`."},
    {"producer": "dhcpapp-ui", "phase": "C", "clone_dir": "DHCPAppUI",
     "clone_url": "https://github.com/pvginkel/DHCPAppUI.git",
     "products": [{"id": "app:dhcpapp-ui", "image": "dhcpapp-ui", "source_repo": "git:pvginkel/DHCPAppUI"}],
     "role": "The web UI for the DHCP app.",
     "special": "Frontend→backend edge: read `../DHCPApp/docs/architecture/architecture.yaml`, find its ApplicationService (svc:…-api,<uuid>), and add `app:dhcpapp-ui —Association→ svc:<that-uuid>`."},
    {"producer": "zigbee-control-ui", "phase": "C", "clone_dir": "ZigbeeControlUI",
     "clone_url": "https://github.com/pvginkel/ZigbeeControlUI.git",
     "products": [{"id": "app:zigbee-control-ui", "image": "zigbee-control-ui", "source_repo": "git:pvginkel/ZigbeeControlUI"}],
     "role": "The web UI for Zigbee control.",
     "special": "Frontend→backend edge: read `../ZigbeeControl/docs/architecture/architecture.yaml`, find its ApplicationService (svc:…-api,<uuid>), and add `app:zigbee-control-ui —Association→ svc:<that-uuid>`."},
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for p in PRODUCERS:
        (OUT / f"{p['producer']}.md").write_text(render(p))
    print(f"Wrote {len(PRODUCERS)} prompts to {OUT}")
    for phase in ("A", "B", "C"):
        ids = [p["producer"] for p in PRODUCERS if p["phase"] == phase]
        print(f"  Phase {phase} ({len(ids)}): {', '.join(ids)}")


if __name__ == "__main__":
    main()
