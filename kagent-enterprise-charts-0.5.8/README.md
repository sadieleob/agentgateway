# kagent-enterprise 0.5.8 Helm charts

The complete set of charts for the kagent-enterprise **0.5.8** install, matching the three
Helm releases on the k3s-milano reference cluster:

| Release (milano) | Chart |
|---|---|
| `kagent-crds` | kagent-enterprise-crds-0.5.8 |
| `kagent` | kagent-enterprise-0.5.8 |
| `kagent-mgmt` | management-0.5.8 |

All pulled anonymously from the official public registries and re-hosted here for transfer.
These are the **official, unmodified** charts.

## Files

| Chart | File | Source (OCI) | sha256 |
|---|---|---|---|
| kagent-enterprise-crds | `kagent-enterprise-crds-0.5.8.tgz` | `us-docker.pkg.dev/solo-public/kagent-enterprise-helm/charts` | `9a83afe84995d760d36fd38705252e1aa84b9d22f5d07d062c37f1926a262005` |
| kagent-enterprise | `kagent-enterprise-0.5.8.tgz` | `us-docker.pkg.dev/solo-public/kagent-enterprise-helm/charts` | `bde9e3211368d60a59bd89772bc153b981ce2326578621f8fd9ca32d8dec1dc3` |
| management (Solo UI) | `management-0.5.8.tgz` | `us-docker.pkg.dev/solo-public/solo-enterprise-helm/charts` | `3fc014e34a8bca3715536fa5fffb8e9c1603732f9156db4cacac6cfb54e76234` |

> `kagent-enterprise-0.5.8.tgz` sha256 (`bde9e3211368d60a59bd89772bc153b981ce2326578621f8fd9ca32d8dec1dc3`) is exactly the OCI blob digest that returned
> 403 on the affected pull environment — same content, intact.

> **`management-0.5.8.tgz` is self-contained:** it bundles its subchart dependencies
> (`management-crds` 0.5.8, `clickhouse` 0.0.11, `agentevals` 0.9.9) inside the tarball, so no
> separate dependency pull / `helm dependency update` is required.

## Download

```bash
git clone https://github.com/sadieleob/agentgateway
cd agentgateway/kagent-enterprise-charts-0.5.8

# or a single file (raw):
curl -L -O https://raw.githubusercontent.com/sadieleob/agentgateway/main/kagent-enterprise-charts-0.5.8/management-0.5.8.tgz
```

## Verify, then push/install

```bash
shasum -a 256 *.tgz   # compare against the table above

# push into an internal chart repo (OCI example)
for f in *.tgz; do helm push "$f" oci://<internal-registry>/<path>; done

# or install/upgrade directly from the files (install order: crds -> mgmt -> enterprise)
helm upgrade -i kagent-crds ./kagent-enterprise-crds-0.5.8.tgz -n kagent
helm upgrade -i kagent-mgmt ./management-0.5.8.tgz            -n kagent -f management-values.yaml
helm upgrade -i kagent      ./kagent-enterprise-0.5.8.tgz     -n kagent -f kagent-values.yaml
```
