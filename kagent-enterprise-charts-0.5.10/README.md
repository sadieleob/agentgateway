# kagent-enterprise 0.5.10 Helm charts

Complete chart set for the kagent-enterprise **0.5.10** install (the three releases:
`kagent-crds`, `kagent`, `kagent-mgmt`). Pulled anonymously from the official public
registries and re-hosted here for transfer. Official, unmodified charts.

> **0.5.10 note:** this release pins the **OSS kagent runtime to `0.10.3` (GA)** — off the
> `0.10.0-rc5` release candidate that 0.5.6–0.5.9 shipped. kagent-tools is `0.3.0`; bundled
> ClickHouse is `26.3.35-alpine`; bundled PostgreSQL is unchanged (`18.6-alpine3.23`).

## Files

| Chart | File | Source (OCI) | sha256 |
|---|---|---|---|
| kagent-enterprise-crds | `kagent-enterprise-crds-0.5.10.tgz` | `us-docker.pkg.dev/solo-public/kagent-enterprise-helm/charts` | `2a2ccfc471912b6061acbde64d9852fa8ea4584bccb38be9ae0ec1fef95b3d9c` |
| kagent-enterprise | `kagent-enterprise-0.5.10.tgz` | `us-docker.pkg.dev/solo-public/kagent-enterprise-helm/charts` | `e8bafc4380f53d0fb2792ccd424608d1a5ad4b68ea13ee6ed2dee048c6201076` |
| management (Solo UI) | `management-0.5.10.tgz` | `us-docker.pkg.dev/solo-public/solo-enterprise-helm/charts` | `f8961bd321e45b18cbd8660c49677daa62e28189b7832b4dd83efe34a101d9f8` |

> `management-0.5.10.tgz` is self-contained: it bundles its subchart dependencies
> (`management-crds`, `clickhouse`, `agentevals`) inside the tarball, so no separate
> dependency pull / `helm dependency update` is required.

## Download

```bash
git clone https://github.com/sadieleob/agentgateway
cd agentgateway/kagent-enterprise-charts-0.5.10
shasum -a 256 *.tgz   # verify against the table above
```

## Push / install

```bash
# push into an internal chart repo (OCI example)
for f in *.tgz; do helm push "$f" oci://<internal-registry>/<path>; done

# or install/upgrade directly (order: crds -> mgmt -> enterprise)
helm upgrade -i kagent-crds ./kagent-enterprise-crds-0.5.10.tgz -n kagent
helm upgrade -i kagent-mgmt ./management-0.5.10.tgz             -n kagent -f management-values.yaml
helm upgrade -i kagent      ./kagent-enterprise-0.5.10.tgz      -n kagent -f kagent-values.yaml
```
