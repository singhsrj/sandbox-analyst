# Infrastructure (Terraform)

Two stages, so powerful credentials never sit on a laptop (ADR-027):

| Stage | Who runs it, where | Creates |
|---|---|---|
| `bootstrap/` | the account owner, once, in **AWS CloudShell** (already signed in, no admin keys created) | IAM user `sandbox-analyst-deployer` with a narrow policy (EC2 in ap-south-1 only, can only launch t4g.small, can only stop/terminate instances tagged `project=sandbox-analyst`), and a monthly cost alarm on real usage (credits excluded) |
| `server/` | the operator machine, as `sandbox-analyst-deployer` | security group (HTTPS/HTTP open, SSH from one IP), SSH key pair, t4g.small Ubuntu 24.04 Arm server (IMDSv2 only, encrypted 20 GB disk, 2 GB swap, Docker), Elastic IP |

Secrets are never Terraform inputs: they would end up in state and in EC2 user data. `deploy/.env` is copied to the server over SSH.

## 1. Bootstrap (account owner, AWS CloudShell)

Open the AWS console in **ap-south-1 (Mumbai)**, click the CloudShell icon, then:

```bash
# Terraform is not preinstalled in CloudShell; this puts 1.16.3 in ~/bin (kept between sessions).
mkdir -p ~/bin && cd ~/bin
curl -fsSLO https://releases.hashicorp.com/terraform/1.16.3/terraform_1.16.3_linux_amd64.zip
curl -fsSL https://releases.hashicorp.com/terraform/1.16.3/terraform_1.16.3_SHA256SUMS | grep linux_amd64.zip | sha256sum -c -
unzip -o terraform_1.16.3_linux_amd64.zip && rm terraform_1.16.3_linux_amd64.zip && export PATH=~/bin:$PATH

git clone https://github.com/singhsrj/sandbox-analyst.git && cd sandbox-analyst/infra/bootstrap
terraform init
terraform apply -var budget_email=you@example.com      # review the plan, type "yes"
```

Then **IAM → Users → sandbox-analyst-deployer → Security credentials → Create access key → Command Line Interface**. On your own machine, open `~/.aws/credentials` in a text editor and add:

```ini
[sandbox-analyst]
aws_access_key_id = AKIA...
aws_secret_access_key = ...
```

(Edit the file yourself; do not paste the secret into a chat or a terminal that is being recorded.) Confirm the budget e-mail subscription AWS sends you.

Keep CloudShell's `terraform.tfstate` (in `infra/bootstrap/`) or download it: it is how the bootstrap resources are changed or removed later.

## 2. Server (operator machine)

```bash
ssh-keygen -t ed25519 -f ~/.ssh/sandbox-analyst -C sandbox-analyst -N ""
cd infra/server
terraform init
terraform apply -var ssh_cidr="$(curl -s https://checkip.amazonaws.com)/32"
```

Wait for first boot (about 3 minutes; `ssh ... test -f /var/lib/cloud/sandbox-analyst-ready`), point the DuckDNS name at `public_ip`, then continue with docs/deploy.md step 2 from "cp .env.production.example".

## Tearing down

`terraform destroy` in `server/` (removes the server and releases the Elastic IP), then in CloudShell `terraform destroy` in `bootstrap/` after deleting the deployer's access key in the console.
