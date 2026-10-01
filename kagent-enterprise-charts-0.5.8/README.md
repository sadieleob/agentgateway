# kagent-enterprise Helm charts v0.5.8

Helm chart tarballs for the kagent-enterprise 0.5.8 upgrade, pulled anonymously from the
official public registry (`oci://us-docker.pkg.dev/solo-public/kagent-enterprise-helm/charts`)
and re-hosted here for transfer. These are the **official, unmodified** charts.

## Files

| Chart | File | sha256 |
|---|---|---|
| kagent-enterprise | `kagent-enterprise-0.5.8.tgz` | `bde9e3211368d60a59bd89772bc153b981ce2326578621f8fd9ca32d8dec1dc3` |
| kagent-enterprise-crds | `kagent-enterprise-crds-0.5.8.tgz` | `9a83afe84995d760d36fd38705252e1aa84b9d22f5d07d062c37f1926a262005` |

> The `kagent-enterprise-0.5.8.tgz` sha256 (`bde9e3211368d60a59bd89772bc153b981ce2326578621f8fd9ca32d8dec1dc3`) is exactly the OCI blob digest that
> returned 403 on the affected pull environment, confirming this is the same content, intact.

## Download

```bash
# via git
git clone https://github.com/sadieleob/agentgateway && cd agentgateway/kagent-enterprise-charts-0.5.8

# or single file (raw)
curl -L -o kagent-enterprise-0.5.8.tgz \
  https://raw.githubusercontent.com/sadieleob/agentgateway/main/kagent-enterprise-charts-0.5.8/kagent-enterprise-0.5.8.tgz
```

## Verify then use

```bash
shasum -a 256 kagent-enterprise-0.5.8.tgz   # must match the table above

# push into an internal chart repo (OCI example)
helm push kagent-enterprise-0.5.8.tgz oci://<internal-registry>/<path>

# or install/upgrade directly from the file
helm upgrade kagent-enterprise ./kagent-enterprise-0.5.8.tgz -n kagent -f values.yaml
```
