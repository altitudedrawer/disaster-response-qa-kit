# Run Jenkins locally (Docker Desktop on macOS)

Jenkins runs in a container. Our pipeline needs `docker build`, so we hand the container
the host's Docker socket: Jenkins then drives your Docker Desktop.

**Before you start:** in Docker Desktop → Settings → Advanced, enable *"Allow the default
Docker socket to be used"*, so that `/var/run/docker.sock` exists.

```bash
cd ~/DisasterResponse/disaster-response-qa-kit

# 1. Build the Jenkins image (Jenkins LTS + Python + Docker CLI + plugins). ~1 GB, first build takes a few minutes.
docker build -t drqa-jenkins jenkins/

# 2. Start it. -u root lets Jenkins use the mounted Docker socket.
#    Fine on your laptop; NEVER do this on a shared server (socket access = root on the host).
docker run -d --name drqa-jenkins -p 8080:8080 -u root \
  -v drqa_jenkins_home:/var/jenkins_home \
  -v /var/run/docker.sock:/var/run/docker.sock \
  drqa-jenkins

# 3. Get the one-time admin password
docker exec drqa-jenkins cat /var/jenkins_home/secrets/initialAdminPassword
```

4. Open http://localhost:8080 and paste the password. Choose *"Select plugins to install"*,
   click **None** (the needed plugins are already in the image), then create your admin user.
5. **New Item** → name `drqa` → **Pipeline** → OK.
6. Under *Pipeline*, set:
   - Definition: **Pipeline script from SCM**
   - SCM: **Git**
   - Repository URL: `https://github.com/altitudedrawer/disaster-response-qa-kit.git` (public, no credentials needed)
   - Branch: `*/main`
   - Script Path: `Jenkinsfile`
7. **Save** → **Build Now**. The first build registers the job's parameter, so later builds
   show **Build with Parameters** instead. (Via the REST API, `/build` then returns HTTP 400
   and you must use `/buildWithParameters`. We hit exactly this while verifying.)
8. To see results, click the build → **Console Output**, or **Test Result** for the JUnit report.

**Optional contract stage:** go to *Manage Jenkins → Credentials → (global) → Add* → kind
*Secret text*, ID `feature-service-url`, value = your layer URL. Then run *Build with
Parameters* with `RUN_CONTRACT_TESTS` ticked.

**Stop / clean up:** `docker rm -f drqa-jenkins` (add `docker volume rm drqa_jenkins_home` to
erase the jobs and settings too).

### What was verified (2026-10-29, Claude's x86_64 cloud sandbox)
- Build #1 on a clean commit: **SUCCESS** in 72 s. All stages ran, the contract stage was
  skipped by its `when`, and the JUnit report showed 81 passed / 3 skipped.
- Build #2 with a deliberately broken test: **FAILURE**. The report showed 1 failed / 80 passed,
  and *Build image* and *Test inside image* were skipped, so no image was produced.
- Sandbox-only differences from the steps above: the setup wizard and security were turned off
  by an init script to automate the run, the repo came from a local git copy instead of GitHub,
  and one extra commit trusted the sandbox's TLS-proxy certificate inside the Docker build.
- **Not verified:** these exact steps on Apple Silicon Docker Desktop (the images are
  multi-arch, but nobody has run it there yet), and the contract stage.
