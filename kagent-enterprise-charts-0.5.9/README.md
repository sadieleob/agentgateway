# kagent-enterprise 0.5.9 Helm charts

Complete chart set for the kagent-enterprise **0.5.9** install (the three releases:
`kagent-crds`, `kagent`, `kagent-mgmt`). Pulled anonymously from the official public
registries and re-hosted here for transfer. Official, unmodified charts.

## Files

| Chart | File | Source (OCI) | sha256 |
|---|---|---|---|
| kagent-enterprise-crds | `kagent-enterprise-crds-0.5.9.tgz` | `us-docker.pkg.dev/solo-public/kagent-enterprise-helm/charts` | `619e22f4ce4c3bdf75592a0c03a91344863b8cde50c278ef5c479bd3a44118ed` |
| kagent-enterprise | `kagent-enterprise-0.5.9.tgz` | `us-docker.pkg.dev/solo-public/kagent-enterprise-helm/charts` | `f61dd39e8b8642144fc0f9e9b0499b601f896aa41a29d532584c23e55e83a6f4` |
| management (Solo UI) | `management-0.5.9.tgz` | `us-docker.pkg.dev/solo-public/solo-enterprise-helm/charts` | `2bc7a5f9fbe7adf22ffbeccc41232b5992bb1132ccdcdcc1f19b8becc2f78895` |

> `management-0.5.9.tgz` is self-contained: it bundles its subchart dependencies
> (`management-crds`, `clickhouse`, `agentevals`) inside the tarball, so no separate
> dependency pull / `helm dependency update` is required.

## Download

```bash
git clone https://github.com/sadieleob/agentgateway
cd agentgateway/kagent-enterprise-charts-0.5.9
shasum -a 256 *.tgz   # verify against the table above
```

## Push / install

```bash
# push into an internal chart repo (OCI example)
for f in *.tgz; do helm push "$f" oci://<internal-registry>/<path>; done

# or install/upgrade directly (order: crds -> mgmt -> enterprise)
helm upgrade -i kagent-crds ./kagent-enterprise-crds-0.5.9.tgz -n kagent
helm upgrade -i kagent-mgmt ./management-0.5.9.tgz            -n kagent -f management-values.yaml
helm upgrade -i kagent      ./kagent-enterprise-0.5.9.tgz     -n kagent -f kagent-values.yaml
```
