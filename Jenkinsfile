// Collects the architecture model of every producer registered in pipeline-producers.yaml,
// validates the federation with the collector, builds the architecture_viewer image that serves it,
// and pins that image into WebathomeOrgDeploy, which Argo CD syncs to prd. It also sets the job's
// own triggers.
//
// The job builds on a push to this repo, and when any registered producer's job succeeds, except
// its own (the self-producer) and those marked `trigger: false`: WebathomeOrgDeploy's, which the
// pin write starts. triggers {} cannot hold a list read at run time, so the Set triggers stage sets
// them, and the build of the commit that registers a producer wires its trigger.
//
// Controller config:
//   - Job: AaC/Architecture
//   - SCM: pvginkel/Architecture, branch main
//   - Script Path: Jenkinsfile

library identifier: 'JenkinsPipelineUtils', changelog: false

pipeline {
    agent {
        kubernetes {
            inheritFrom 'jenkins-agent kaniko'
            yamlMergeStrategy merge()
            yaml podYaml(templates: ['k8s', 'python'])
        }
    }

    options {
        disableConcurrentBuilds(abortPrevious: true)
        skipDefaultCheckout()
        timeout(time: 60, unit: 'MINUTES')
        timestamps()
        // A push that reaches many producer repos finishes their jobs in a burst, and a build for
        // each would only be aborted by the next.
        quietPeriod(90)
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        // The estate's one properties step. Declarative leaves alone the triggers its
        // triggers {} did not declare, so the next build keeps these.
        stage('Set triggers') {
            steps {
                script {
                    List producers = readYaml(file: 'pipeline-producers.yaml').producers ?: []
                    // A job that publishes for several producers is named once.
                    List upstreamJobs = []
                    for (producer in producers) {
                        if (!producer.self && producer.trigger != false && !upstreamJobs.contains(producer.jenkinsJob)) {
                            upstreamJobs << producer.jenkinsJob
                        }
                    }
                    List jobTriggers = [githubPush()]
                    if (upstreamJobs) {
                        jobTriggers << upstream(threshold: hudson.model.Result.SUCCESS, upstreamProjects: upstreamJobs.join(', '))
                    }
                    properties([pipelineTriggers(jobTriggers)])
                }
            }
        }

        stage('Collect producer artifacts') {
            steps {
                script {
                    List producers = readYaml(file: 'pipeline-producers.yaml').producers ?: []
                    Map producersOfJob = [:]
                    for (producer in producers) {
                        producersOfJob[producer.jenkinsJob] = (producersOfJob[producer.jenkinsJob] ?: 0) + 1
                    }
                    for (producer in producers) {
                        if (producer.self) {
                            // The self-producer's artifact is this checkout's docs/architecture/:
                            // its job's last successful build is this job's previous build.
                            sh """
                                set -eu
                                mkdir -p 'producer-artifacts/${producer.id}/docs/architecture'
                                cp docs/architecture/*.yaml 'producer-artifacts/${producer.id}/docs/architecture/'
                            """
                        } else {
                            // A job that publishes for several producers archives each one's
                            // <id>.yaml, and the collector refuses a file that names another
                            // producer than its directory's.
                            String filter = producersOfJob[producer.jenkinsJob] > 1 ? "**/architecture/${producer.id}.yaml" : '**/architecture/**/*.yaml'
                            copyArtifacts(
                                projectName: producer.jenkinsJob,
                                selector: lastSuccessful(),
                                filter: filter,
                                target: "producer-artifacts/${producer.id}",
                                fingerprintArtifacts: true
                            )
                        }
                    }
                }
                // The collector's inputs, archived before it runs, so that a failed collection can be
                // replayed from them.
                sh 'tar -czf producer-artifacts.tgz producer-artifacts'
                archiveArtifacts artifacts: 'producer-artifacts.tgz', fingerprint: true
            }
        }

        stage('Validate architecture') {
            steps {
                container('python') {
                    // --relaxed tolerates dangling references between producers while the
                    // federation is onboarding. The Dockerfile's run-collector stage passes the same
                    // flag, and the two runs must match.
                    sh '''
                        set -eu
                        pip install --quiet --no-cache-dir poetry
                        cd tooling
                        poetry install --no-root --without dev
                        poetry run python collect.py \
                            --producers "$WORKSPACE/pipeline-producers.yaml" \
                            --in "$WORKSPACE/producer-artifacts" \
                            --out "$WORKSPACE/dist" \
                            --relaxed
                    '''
                }
                archiveArtifacts artifacts: 'dist/data/v0.1/validation-report.json', fingerprint: true
            }
        }

        stage('Build architecture_viewer image') {
            steps {
                // The image bundles producer-artifacts/, which .dockerignore keeps out of every other
                // build of the Dockerfile.
                sh '''
                    set -eu
                    grep -v '^producer-artifacts/$' .dockerignore > .dockerignore.tmp || true
                    mv .dockerignore.tmp .dockerignore
                '''
                container('kaniko') {
                    script {
                        helmCharts.kaniko2(destinations: [
                            "registry:5000/architecture_viewer:${currentBuild.number}",
                            'registry:5000/architecture_viewer:latest',
                        ])
                    }
                }
            }
        }

        stage('Write image pins') {
            steps {
                container('k8s') {
                    script {
                        cicd.writeVersionPins(repo: 'pvginkel/WebathomeOrgDeploy', pins: [
                            'config/prd/values.yaml': ['images.architecture_viewer': ":${currentBuild.number}"],
                        ])
                    }
                }
            }
        }
    }
}
