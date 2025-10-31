cat > docs/CI-CD-SETUP-GUIDE.md <<'EOF'
# CI/CD Pipeline Setup Guide

## 🎯 Goal
Set up a fully automated CI/CD pipeline that:
1. Builds a custom Minecraft Docker image when code changes
2. Pushes the image to Docker Hub
3. Updates Kubernetes manifests automatically
4. ArgoCD detects changes and deploys to K3s cluster

## 📊 End Output
```
Code Change → GitHub Actions → Docker Hub → Git Update → ArgoCD → K3s Cluster
     ↓              ↓              ↓            ↓          ↓          ↓
  Push Dockerfile  Build Image   Store Image  Update YAML Sync     Deploy
```

After setup, any change to `docker/minecraft/` triggers automatic rebuild and deployment with zero manual intervention.

---

## ✅ Prerequisites Checklist

Before starting, ensure you have:

- [ ] GitHub account with repository access
- [ ] Docker Hub account
- [ ] K3s cluster running
- [ ] ArgoCD installed in cluster
- [ ] kubectl access to cluster
- [ ] Git configured locally

---

## 📝 Step-by-Step Setup

### Step 1: Create Docker Hub Account & Token

#### 1.1 Sign Up for Docker Hub
1. Go to: https://hub.docker.com/signup
2. Create account (use same username everywhere for consistency)
3. Verify email

**Example:**
- Username: `haziqishere`
- Email: `your.email@example.com`

#### 1.2 Create Access Token
1. Login to Docker Hub
2. Click your **profile icon** (top right) → **Account Settings**
3. Click **Security** tab
4. Click **New Access Token**
5. Fill in:
   - **Access Token Description**: `GitHub Actions - Minecraft CI`
   - **Access permissions**: Select **Read, Write, Delete**
6. Click **Generate Token**
7. **IMPORTANT**: Copy the token immediately (format: `dckr_pat_xxxxxxxxxxxxx`)
8. Save it temporarily in a secure note

**⚠️ You won't see this token again!**

---

### Step 2: Add Docker Credentials to GitHub Secrets

#### 2.1 Navigate to Repository Settings
1. Go to your GitHub repo: `https://github.com/YOUR_USERNAME/minecraft-kubernetes`
2. Click **Settings** tab (top navigation)
3. In left sidebar, click **Secrets and variables** → **Actions**

#### 2.2 Add Docker Username Secret
1. Click **New repository secret** (green button)
2. Fill in:
   - **Name**: `DOCKER_USERNAME`
   - **Secret**: Your Docker Hub username (e.g., `haziqishere`)
3. Click **Add secret**

#### 2.3 Add Docker Token Secret
1. Click **New repository secret** again
2. Fill in:
   - **Name**: `DOCKER_TOKEN`
   - **Secret**: Paste the token from Step 1.2
3. Click **Add secret**

#### 2.4 Verify Secrets
You should now see:
```
DOCKER_USERNAME  •••••••••••  Updated X seconds ago
DOCKER_TOKEN     •••••••••••  Updated X seconds ago
```

---

### Step 3: Update Docker Hub Username in Files

Replace `haziqishere` with YOUR Docker Hub username in these files:

#### 3.1 Update GitHub Workflow
File: `.github/workflows/build-minecraft.yaml`

**No changes needed** - it uses `${{ secrets.DOCKER_USERNAME }}`

#### 3.2 Update Kubernetes Deployment
File: `kubernetes/minecraft/deployment.yaml`

Find this line:
```yaml
image: haziqishere/minecraft-custom:latest
```

Change to:
```yaml
image: YOUR_DOCKERHUB_USERNAME/minecraft-custom:latest
```

#### 3.3 Update Makefile (Optional)
File: `Makefile`

Search for `haziqishere` and replace with your username if needed.

---

### Step 4: Configure ArgoCD Repository Access

ArgoCD needs access to your GitHub repository.

#### Option A: Public Repository (Easiest)

If your repo is public:
```bash
# No authentication needed!
# Just apply the ArgoCD application
kubectl apply -f kubernetes/argocd/application.yaml
```

#### Option B: Private Repository via SSH

1. **Generate SSH Key**
```bash
ssh-keygen -t ed25519 -C "argocd@kroni-smp" -f ~/.ssh/argocd-github -N ""
```

2. **Add Public Key to GitHub**
```bash
# Copy public key
cat ~/.ssh/argocd-github.pub
```

Then:
- Go to your repo: Settings → Deploy keys
- Click **Add deploy key**
- Title: `ArgoCD Kroni-SMP`
- Paste the public key
- Click **Add key**

3. **Add Repository to ArgoCD**
```bash
# Get ArgoCD password
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" | base64 -d; echo

# Login to ArgoCD
argocd login kroni-smp.taile695bc.ts.net:30081 \
  --username admin \
  --password YOUR_PASSWORD \
  --insecure

# Add repository
argocd repo add git@github.com:YOUR_USERNAME/minecraft-kubernetes.git \
  --ssh-private-key-path ~/.ssh/argocd-github \
  --insecure-skip-server-verification
```

4. **Verify Connection**
```bash
argocd repo list

# Should show:
# REPO                                          TYPE  STATUS      
# git@github.com:YOUR_USERNAME/minecraft...    git   Successful
```

---

### Step 5: Apply ArgoCD Application
```bash
# Apply the ArgoCD application
kubectl apply -f kubernetes/argocd/application.yaml

# Verify it's created
kubectl get application -n argocd

# Should show:
# NAME        SYNC STATUS   HEALTH STATUS
# minecraft   Synced        Healthy
```

---

### Step 6: Test the Pipeline

#### 6.1 Make a Test Change
```bash
cd ~/Projects/server/minecraft-kubernetes

# Edit Dockerfile to trigger build
nano docker/minecraft/Dockerfile

# Change something, like:
# ENV VIEW_DISTANCE=10
# to
# ENV VIEW_DISTANCE=12

# Commit and push
git add docker/minecraft/Dockerfile
git commit -m "test: update view distance to 12"
git push origin main
```

#### 6.2 Watch GitHub Actions
1. Go to: `https://github.com/YOUR_USERNAME/minecraft-kubernetes/actions`
2. You should see a new workflow running
3. Click on it to watch progress

**Expected steps:**
1. ✅ Checkout code
2. ✅ Set up Docker Buildx
3. ✅ Login to Docker Hub
4. ✅ Extract metadata
5. ✅ Build and push Docker image
6. ✅ Update deployment manifest
7. ✅ Commit and push changes

#### 6.3 Verify Docker Hub
1. Go to: `https://hub.docker.com/r/YOUR_USERNAME/minecraft-custom/tags`
2. You should see new tags:
   - `latest`
   - `main-abc1234` (Git SHA)

#### 6.4 Watch ArgoCD Deployment
```bash
# Watch ArgoCD sync
watch kubectl get application -n argocd

# Watch Minecraft pod update
watch kubectl get pods -n minecraft

# You'll see:
# - Old pod terminating
# - New pod creating
# - New pod running with updated image
```

#### 6.5 Verify New Image
```bash
# Check which image is running
kubectl get deployment minecraft-server -n minecraft -o jsonpath='{.spec.template.spec.containers[0].image}'

# Should show: YOUR_USERNAME/minecraft-custom:main-abc1234
```

---

## 🔍 Verification Checklist

After setup, verify everything works:

- [ ] GitHub secrets are set (`DOCKER_USERNAME`, `DOCKER_TOKEN`)
- [ ] Docker Hub username updated in all files
- [ ] ArgoCD can access GitHub repository
- [ ] ArgoCD application is created and synced
- [ ] Test commit triggers GitHub Actions
- [ ] Docker image builds and pushes successfully
- [ ] GitHub Actions commits updated YAML
- [ ] ArgoCD detects change and syncs
- [ ] New Minecraft pod starts with new image

---

## 🐛 Troubleshooting

### Error: "Username and password required"

**Problem:** Docker Hub credentials not configured in GitHub secrets

**Solution:**
1. Check secrets exist: Repo → Settings → Secrets → Actions
2. Verify names are EXACTLY: `DOCKER_USERNAME` and `DOCKER_TOKEN` (case-sensitive)
3. Re-create secrets if needed
4. Retry workflow: Actions → Failed workflow → Re-run jobs

### Error: "Permission denied (publickey)"

**Problem:** ArgoCD can't access private GitHub repo

**Solution:**
1. Verify SSH key added to GitHub deploy keys
2. Test SSH key locally:
```bash
ssh -T git@github.com -i ~/.ssh/argocd-github
# Should say: "Hi USERNAME! You've successfully authenticated"
```
3. Re-add repository to ArgoCD

### Error: "Application sync failed"

**Problem:** ArgoCD application pointing to wrong path

**Solution:**
```bash
# Check application status
kubectl describe application minecraft -n argocd

# Delete and recreate
kubectl delete application minecraft -n argocd
kubectl apply -f kubernetes/argocd/application.yaml
```

### Build succeeds but pod doesn't update

**Problem:** Image tag in deployment didn't update

**Solution:**
1. Check if GitHub Actions committed changes:
   - Go to repo commits
   - Look for commit from `github-actions[bot]`
2. Manually trigger ArgoCD sync:
```bash
argocd app sync minecraft
```

---

## 📊 Expected Timelines

| Action | Time |
|--------|------|
| GitHub Actions build | 3-5 minutes |
| Docker Hub push | 30-60 seconds |
| ArgoCD detection | 3 minutes (default) |
| Pod restart | 1-2 minutes |
| **Total deployment time** | **~7-10 minutes** |

---

## 🔄 Daily Workflow

After setup, your workflow is simple:
```bash
# 1. Make changes
cd docker/minecraft/mods
# Add a new mod JAR file

# 2. Commit and push
git add .
git commit -m "feat: add new mod"
git push

# 3. Wait ~7-10 minutes
# Everything else is automatic!

# 4. Verify (optional)
make status
```

---

## 🎮 Testing Minecraft Connection

After deployment completes:
```bash
# Check pod is running
kubectl get pods -n minecraft

# Check logs
kubectl logs -n minecraft -l app=minecraft --tail=50

# Connect from Minecraft client
# Server address: kroni-smp.taile695bc.ts.net:30565
```

---

## 📚 Additional Resources

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Docker Hub Docs](https://docs.docker.com/docker-hub/)
- [ArgoCD Getting Started](https://argo-cd.readthedocs.io/en/stable/getting_started/)
- [Minecraft Docker Image](https://github.com/itzg/docker-minecraft-server)

---

## 🆘 Need Help?

If you encounter issues:

1. Check GitHub Actions logs for build errors
2. Check ArgoCD UI for sync status
3. Check pod logs: `kubectl logs -n minecraft -l app=minecraft`
4. Review this guide's troubleshooting section

---

## 🎉 Success Criteria

You know it's working when:

✅ Pushing code triggers automatic build  
✅ Image appears in Docker Hub with new tag  
✅ ArgoCD detects and syncs changes  
✅ Minecraft pod restarts with new image  
✅ Players can connect to updated server  

**Congratulations! You now have a production-grade CI/CD pipeline!** 🚀
EOF

# Also create a quick reference card
cat > docs/QUICK-REFERENCE.md <<'EOF'
# CI/CD Quick Reference

## 🔑 Required Secrets (GitHub)

| Secret Name | Value | Where to Get |
|-------------|-------|--------------|
| `DOCKER_USERNAME` | Your Docker Hub username | Docker Hub account |
| `DOCKER_TOKEN` | Docker Hub access token | Docker Hub → Settings → Security |

## 📝 Files to Update

Replace `haziqishere` with YOUR username:

1. `kubernetes/minecraft/deployment.yaml` - Line with `image:`
2. `Makefile` - (optional) Search and replace

## 🚀 Quick Setup Commands
```bash
# 1. Add secrets to GitHub
# (Done via GitHub UI - see main guide)

# 2. Update deployment image
sed -i 's/haziqishere/YOUR_USERNAME/g' kubernetes/minecraft/deployment.yaml

# 3. Setup ArgoCD repo access (if private)
ssh-keygen -t ed25519 -C "argocd" -f ~/.ssh/argocd-github -N ""
cat ~/.ssh/argocd-github.pub
# Add to GitHub → Repo → Settings → Deploy keys

# 4. Add repo to ArgoCD
argocd repo add git@github.com:YOUR_USERNAME/minecraft-kubernetes.git \
  --ssh-private-key-path ~/.ssh/argocd-github

# 5. Apply ArgoCD app
kubectl apply -f kubernetes/argocd/application.yaml

# 6. Test with a change
echo "# test" >> docker/minecraft/Dockerfile
git add . && git commit -m "test: trigger pipeline" && git push
```

## ✅ Verification Commands
```bash
# Check GitHub Actions
open https://github.com/YOUR_USERNAME/minecraft-kubernetes/actions

# Check Docker Hub
open https://hub.docker.com/r/YOUR_USERNAME/minecraft-custom/tags

# Check ArgoCD sync
kubectl get application -n argocd

# Check pod status
kubectl get pods -n minecraft

# Check deployed image
kubectl get deployment minecraft-server -n minecraft -o jsonpath='{.spec.template.spec.containers[0].image}'
```

## 🐛 Common Fixes
```bash
# Rerun failed GitHub Action
# Go to Actions → Failed run → Re-run all jobs

# Force ArgoCD sync
argocd app sync minecraft

# Restart Minecraft pod
kubectl rollout restart deployment minecraft-server -n minecraft

# Check logs
kubectl logs -n minecraft -l app=minecraft --tail=100
```
EOF

echo "✅ Documentation created!"
echo ""
echo "📄 Created files:"
echo "  - docs/CI-CD-SETUP-GUIDE.md  (Complete guide)"
echo "  - docs/QUICK-REFERENCE.md     (Quick commands)"
echo ""
echo "Read docs/CI-CD-SETUP-GUIDE.md for full instructions!"