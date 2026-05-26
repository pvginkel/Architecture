library('JenkinsPipelineUtils') _

podTemplate(inheritFrom: 'jenkins-agent kaniko') {
    node(POD_LABEL) {
        stage('Cloning repo') {
            checkout scm
        }

        stage('Build architecture viewer') {
            container('kaniko') {
                helmCharts.kaniko([
                    "registry:5000/architecture_viewer:${currentBuild.number}",
                    'registry:5000/architecture_viewer:latest'
                ])
            }
        }

        stage('Redeploy home') {
            build job: 'HelmCharts', wait: false
        }
    }
}
