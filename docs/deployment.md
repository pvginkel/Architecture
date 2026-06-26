# Deployment context

The Architecture stack is self-hosted: Kubernetes, Jenkins, Kaniko, Ansible. The deliverable
from this repo is the **container artifact** — the `service/` image that serves the viewer bundle
and the published dataset, built by `Dockerfile` / `Jenkinsfile`. The K8s manifests, Jenkins
jobs, and Ansible glue that deploy it are the operator's, living in the `HelmCharts` / `Ansible`
repos.

- Don't propose hosting alternatives or redesign the CI/CD. Focus on the container artifact;
  the K8s/Jenkins glue is the operator's.
- The viewer is served from the container at `architecture.webathome.org/viewer/` and
  iframe-embedded into webathome.org.
