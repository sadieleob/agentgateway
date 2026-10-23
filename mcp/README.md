# MCP auth patterns with Solo Enterprise for agentgateway

Configurations for fronting remote MCP servers with agentgateway, split by how the upstream
credential is obtained. **Only setups that were tested end to end are kept here**, each with the
version and date it was verified.

| Folder | Pattern | Who logs in to the SaaS | Upstream token lives on |
|---|---|---|---|
| [`elicitation/`](./elicitation/) | Gateway-brokered OAuth ("dual auth"): users sign in to the gateway with Entra, the gateway runs the per-user SaaS consent and injects the SaaS token | The gateway (browser consent once per user per SaaS) | Gateway token service (encrypted, Postgres) |
| [`passthrough/`](./passthrough/) | The MCP client does the SaaS OAuth itself; the gateway forwards the token | The MCP client | Each client |

All values that identify a tenant, app, host or credential are `REPLACE_WITH_*` placeholders.
