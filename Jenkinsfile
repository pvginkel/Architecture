// Architecture-rebuild pipeline (v3).
//
// 1. Checkout the Architecture repo.
// 2. Read pipeline-producers.yaml — the registered producer list.
// 3. For each registered producer:
//    - if `jenkinsJob` is set: copyArtifacts from <jenkinsJob>
//      lastSuccessful into producer-artifacts/<producer-id>/;
//    - if `jenkinsJob` is absent: this is a self-producer whose
//      source lives in docs/architecture/ of this very repo; copy
//      those files into producer-artifacts/<producer-id>/.
// 4. Bundle producer-artifacts/ into producer-artifacts.tgz and
//    archive it as a build artifact, before the collector runs, so
//    the raw inputs are available for debugging even on failure.
// 5. Run the collector (`tooling/collect.py`) in a Python sidecar to
//    archive validation-report.json as a Jenkins build artifact.
// 6. Clear the `producer-artifacts/` line in .dockerignore so kaniko
//    sees the populated directory.
// 7. Kaniko-build the multi-stage Dockerfile. The Dockerfile's
//    `run-collector` stage reruns collect.py against the same inputs
//    inside the image; output is byte-identical to step 5 by the
//    collector's determinism guarantee.
// 8. Trigger the Helm-side redeploy job (unchanged from v2).
//
// Triggers wired below:
//   - SCM push to this repo (the default poll-or-webhook).
//   - Upstream success of every registered producer's Jenkins job.
//     In v3 pipeline-producers.yaml ships empty, so no upstream
//     triggers are wired yet; v4 producer onboarding automatically
//     wires them via the next Jenkinsfile execution.
//   - Manual "Build Now" in the Jenkins UI is always available.

library identifier: 'JenkinsPipelineUtils', changelog: false

podTemplate(inheritFrom: 'jenkins-agent kaniko', containers: [
    containerTemplates.python('python')
]) {
    node(POD_LABEL) {
        stage('Checkout') {
            checkout scm
        }

        // Triggers wiring derived from pipeline-producers.yaml.
        def producersDoc = readYaml(file: 'pipeline-producers.yaml')
        def producers = producersDoc.producers ?: []
        def upstreamJobs = producers.collect { it.jenkinsJob }.findAll { it != null }.join(', ')

        def triggers = [githubPush()]
        if (upstreamJobs) {
            triggers << upstream(threshold: hudson.model.Result.SUCCESS,
                                 upstreamProjects: upstreamJobs)
        }
        properties([pipelineTriggers(triggers)])

        stage('Copy producer artifacts') {
            sh 'mkdir -p producer-artifacts'
            producers.each { p ->
                if (p.jenkinsJob) {
                    copyArtifacts(
                        projectName: p.jenkinsJob,
                        selector: lastSuccessful(),
                        filter: '**/architecture/**/*.yaml',
                        target: "producer-artifacts/${p.id}",
                        fingerprintArtifacts: true
                    )
                } else {
                    // Self-producer: source lives in this repo under
                    // docs/architecture/. Mirror the directory into
                    // producer-artifacts/<id>/ so the collector's
                    // rglob walk picks the files up the same way it
                    // does for upstream producers.
                    sh """
                        set -eu
                        mkdir -p producer-artifacts/${p.id}/docs/architecture
                        cp docs/architecture/*.yaml producer-artifacts/${p.id}/docs/architecture/
                    """
                }
            }
        }

        stage('Archive collected artifacts') {
            // Debugging aid: bundle the raw producer-artifacts/ tree
            // and expose it as a build artifact before the collector
            // runs, so the inputs are available even if collection
            // fails downstream.
            sh '''
                set -eu
                tar -czf producer-artifacts.tgz producer-artifacts
            '''
            archiveArtifacts(
                artifacts: 'producer-artifacts.tgz',
                fingerprint: true,
                allowEmptyArchive: false
            )
        }

        stage('Run collector') {
            container('python') {
                sh '''
                    set -eu
                    pip install --quiet --no-cache-dir poetry
                    cd tooling
                    poetry install --no-root --without dev
                    poetry run python collect.py \
                        --producers "${WORKSPACE}/pipeline-producers.yaml" \
                        --in "${WORKSPACE}/producer-artifacts" \
                        --out "${WORKSPACE}/dist" \
                        --relaxed
                    # --relaxed tolerates dangling cross-producer refs while the
                    # federation is still onboarding (apps whose owning producer
                    # isn't emitting yet). The Dockerfile's run-collector stage
                    # carries the same flag (the two runs must match); drop it
                    # from BOTH once every referenced producer is online so
                    # dangling refs fail the build again.
                '''
            }
            archiveArtifacts(
                artifacts: 'dist/data/v0.1/validation-report.json',
                fingerprint: true,
                allowEmptyArchive: false
            )
        }

        stage('Build container image') {
            // The pipeline opts in to bundling producer-artifacts/ by
            // dropping its exclusion from .dockerignore. The collector
            // step above already validated everything.
            sh '''
                set -eu
                if [ -f .dockerignore ]; then
                    grep -v '^producer-artifacts/$' .dockerignore > .dockerignore.tmp || true
                    mv .dockerignore.tmp .dockerignore
                fi
            '''
            container('kaniko') {
                helmCharts.kaniko([
                    "registry:5000/architecture_viewer:${currentBuild.number}",
                    'registry:5000/architecture_viewer:latest'
                ])
            }
        }

        stage('Redeploy home') {
            cicd.helmDeploy()
        }
    }
}
