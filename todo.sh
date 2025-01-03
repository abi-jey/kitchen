sudo kubeadm init phase certs all -v=5
sudo kubeadm init phase kubeconfig all -v=5
sudo kubeadm init phase etcd local -v=5
sudo kubeadm init phase control-plane apiserver -v=5
sudo kubeadm init phase control-plane controller-manager -v=5
sudo kubeadm init phase control-plane scheduler -v=5

# Here we Update /etc/kubernetes/manisfest/kube-apiserver.yaml to add ",PodTolerationRestriction"
sudo sed -i '/--enable-admission-plugins/s/$/,PodTolerationRestriction/' /etc/kubernetes/manifests/kube-apiserver.yaml

sudo kubeadm init phase kubelet-start --cri-socket unix:///var/run/crio/crio.sock -v=5
sudo kubeadm init phase upload-config all --cri-socket unix:///var/run/crio/crio.sock -v=5
sudo kubeadm init phase upload-certs --upload-certs -v=5
sudo kubeadm init phase mark-control-plane -v=5
sudo kubeadm init phase bootstrap-token -v=5
sudo kubeadm init phase kubelet-finalize --all -v=5
sudo kubeadm init phase addon all -v=5
sudo kubeadm init phase show-join-command -v=5

# Add the annotation for default toleration for all taints to the kube-system,default namespace
kubectl annotate namespace kube-system scheduler.alpha.kubernetes.io/defaultTolerations='[{"operator":"Exists", "effect":"NoSchedule"}]'
kubectl annotate namespace default scheduler.alpha.kubernetes.io/defaultTolerations='[{"operator":"Exists", "effect":"NoSchedule"}]'

# load metrics server and modify to be able to run insure ssl mode
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
kubectl patch deployment metrics-server -n kube-system --type='json' -p='[{"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--kubelet-insecure-tls"}]'

# install local-path-provisioner and make it default storage class
kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/v0.0.30/deploy/local-path-storage.yaml
kubectl patch storageclass local-path -p '{"metadata": {"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}'
# patch namespac "local-path-storage" to to have default toleration for all taints
kubectl patch namespace local-path-storage -p '{"metadata": {"annotations":{"scheduler.alpha.kubernetes.io/defaultTolerations":"[{\"operator\":\"Exists\", \"effect\":\"NoSchedule\"}]"}}}'


# install prometheus via helm
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm install prometheus prometheus-community/prometheus

# install cilium
cilium install --version 1.16.5

# Run basic Tests

# 1. Deploy and ubuntu pod and check if it is running, remove afterwards
kubectl run -i --tty ubuntu --image=ubuntu:20.04 --restart=Never -- bash -il


echo "Kubeadm init completed successfully, the kubeconfig file is located at /etc/kubernetes/admin.conf, move and change permission via sudo cp /etc/kubernetes/admin.conf $HOME/.kube/config && sudo chown $(id -u):$(id -g) $HOME/.kube/config"


# kubelet-start                 Write kubelet settings and (re)start the kubelet
# upload-config                 Upload the kubeadm and kubelet configuration to a ConfigMap
#   /kubeadm                      Upload the kubeadm ClusterConfiguration to a ConfigMap
#   /kubelet                      Upload the kubelet component config to a ConfigMap
# upload-certs                  Upload certificates to kubeadm-certs
# mark-control-plane            Mark a node as a control-plane
# bootstrap-token               Generates bootstrap tokens used to join a node to a cluster
# kubelet-finalize              Updates settings relevant to the kubelet after TLS bootstrap
#   /enable-client-cert-rotation  Enable kubelet client certificate rotation
#   /experimental-cert-rotation   Enable kubelet client certificate rotation (DEPRECATED: use 'enable-client-cert-rotation' instead)
# addon                         Install required addons for passing conformance tests
#   /coredns                      Install the CoreDNS addon to a Kubernetes cluster
#   /kube-proxy                   Install the kube-proxy addon to a Kubernetes cluster
# show-join-command 