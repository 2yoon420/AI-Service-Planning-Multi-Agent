# CI/CD 설정 안내

- **작성일**: 2026-07-28
- **워크플로**: `.github/workflows/ci-cd.yml`
- **전제**: 2026-07-28 수동 배포가 성공한 상태 (`배포_가이드.md` 완료)

## 0. 이 워크플로가 하는 일

```
push (모든 브랜치·PR)
   └─ test  : pytest 92개 + 프론트 tsc·빌드
                 │  통과해야만
main push     ↓
   └─ deploy: IAP 터널로 VM 접속 → deploy/deploy.sh 실행 → 공개 URL /api/health 확인
```

**배포를 워크플로에서 재구현하지 않았습니다.** 서버의 `deploy.sh`를 그대로 부릅니다.
그 스크립트는 사람이 직접 돌려 성공한 절차이고, 코드 경로가 하나여야 *"수동은 되는데
CI만 실패"* 같은 상황이 생기지 않습니다.

## 1. 사용자님이 직접 하셔야 하는 것

자격증명을 다루는 일이라 제가 대신 할 수 없습니다.

### 1-1. 배포용 서비스 계정 생성

> **이 GCP 프로젝트(`clean-skill-501705-t4`)는 동료 팀의 Text-to-SQL 프로젝트와 공유됩니다.**
> 기존 `github-deployer` 계정이 이미 있지만 재사용하지 않습니다. 그 계정은
> `run.admin`·`artifactregistry.writer`·`compute.instanceAdmin.v1`까지 갖고 있어서,
> 우리 저장소가 뚫리면 상대 프로젝트의 Cloud Run까지 닿습니다. 전용 계정을 따로 만들어
> **VM 접속과 서비스 재시작 외에는 아무것도 못 하게** 제한합니다.

```bash
export PROJECT_ID=$(gcloud config get-value project)
export SA=planner-deployer

gcloud iam service-accounts create $SA --display-name="현장미러링 배포"

# IAP 터널 통과
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/iap.tunnelResourceAccessor"

# VM 접속 (OS Login) — Admin이어야 한다. 이유는 바로 아래 참고.
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/compute.osAdminLogin"

# VM 조회
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/compute.viewer"
```

> **왜 `osLogin`이 아니라 `osAdminLogin`인가**
>
> 배포 스텝이 `sudo -u planner bash deploy.sh`를 부릅니다. `osLogin`만 주면 접속한
> 계정에 sudo 권한이 없어 **이 줄에서 바로 실패**합니다(`user is not in the sudoers file`).
> `osAdminLogin`이 있어야 sudo를 쓸 수 있습니다.
>
> 대신 **권한 계층을 두 단계로 나눠** 위험을 줄입니다.
>
> | 주체 | 할 수 있는 것 |
> |---|---|
> | CI 접속 계정 (osAdminLogin) | sudo 전반 — 다만 하는 일은 `sudo -u planner`로 즉시 내려가는 것뿐 |
> | `planner` 사용자 | 1-3절에서 연 **세 명령만** root로 실행 |
>
> 실제 배포 작업은 전부 권한이 낮은 `planner`로 수행되고, root가 필요한 지점은
> 서비스 재시작 3종으로 한정됩니다.

### 1-2. Workload Identity Federation 연결 — **키를 만들지 않습니다**

서비스 계정 키(JSON)를 발급해 GitHub에 넣는 방식도 있지만 쓰지 않습니다. 그 키는
**만료가 없어서**, 유출되면 사람이 알아채고 폐기할 때까지 계속 유효합니다. WIF는
GitHub이 발급한 OIDC 토큰을 GCP가 직접 검증하고 **수십 분이면 만료되는** 단기 토큰으로
바꿔 줍니다. 저장할 비밀 자체가 없습니다.

```bash
export POOL=github-pool          # 기존 풀을 재사용한다 (아래 설명)
export PROVIDER=planner-provider # 우리 전용 공급자
export REPO=2yoon420/AI-Service-Planning-Multi-Agent
export PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')

# 필요한 API
gcloud services enable iamcredentials.googleapis.com sts.googleapis.com

# ① 풀은 이미 있다 — 없을 때만 만든다
gcloud iam workload-identity-pools describe $POOL --location=global >/dev/null 2>&1 \
  || gcloud iam workload-identity-pools create $POOL \
       --location=global --display-name="GitHub Actions"

# ② 공급자 등록 — attribute-condition이 이 설정의 핵심 안전장치다
gcloud iam workload-identity-pools providers create-oidc $PROVIDER \
  --location=global --workload-identity-pool=$POOL \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository=='${REPO}'"

# ③ 이 저장소에서 온 요청만 서비스 계정을 빌릴 수 있게 묶는다
gcloud iam service-accounts add-iam-policy-binding \
  "${SA}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}/attribute.repository/${REPO}"
```

> **풀은 공유해도 되지만 공급자는 나눠야 합니다.**
>
> 이 프로젝트에는 동료 팀이 만든 풀 `github-pool`과 공급자 `github-provider`가 이미 있고,
> 그 공급자의 조건절은 `Doyunamic-Kwon/edu-gachon2026-project`로 못박혀 있습니다. 그대로
> 쓰면 우리 저장소 요청은 거부됩니다. 조건절을 넓혀 두 저장소를 다 받게 하면 한쪽의 사고가
> 다른 쪽으로 번지므로, **같은 풀 안에 우리 전용 공급자(`planner-provider`)를 추가**합니다.
> 풀은 그릇일 뿐이고 실제 접근 통제는 공급자의 조건절이 합니다.
>
> 기존 공급자는 절대 수정하지 마십시오 — 동료 팀의 배포가 멈춥니다.

> **`--attribute-condition`을 빼지 마십시오.** 이게 없으면 *어떤 GitHub 저장소에서 온
> 요청이든* 이 서비스 계정을 빌릴 수 있습니다. 남의 저장소에서도 우리 GCP 프로젝트에
> 배포할 수 있게 된다는 뜻입니다. WIF의 안전성은 토큰이 짧다는 점보다 **이 조건절**에서
> 나옵니다.
>
> 마찬가지로 ③의 `--member`도 `attribute.repository/${REPO}`로 저장소를 못박습니다.
> 여기에 풀 전체(`principalSet://.../workloadIdentityPools/${POOL}/*`)를 넣으면 조건절이
> 무의미해집니다.

등록에 쓸 값을 출력합니다.

```bash
echo "GCP_WIF_PROVIDER = projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}/providers/${PROVIDER}"
echo "GCP_SA_EMAIL     = ${SA}@${PROJECT_ID}.iam.gserviceaccount.com"
```

GitHub 저장소 → **Settings → Secrets and variables → Actions → Variables** 탭

| 종류 | 이름 | 값 |
|---|---|---|
| Variable | `GCP_WIF_PROVIDER` | 위에서 출력된 `projects/.../providers/github-provider` |
| Variable | `GCP_SA_EMAIL` | `github-deployer@<PROJECT_ID>.iam.gserviceaccount.com` |
| Variable | `GCP_ZONE` | `asia-northeast3-a` |
| Variable | `GCP_VM` | `planner-vm` |
| Variable | `SITE_URL` | `https://<VM외부IP>.sslip.io` |

**Secret은 하나도 없습니다.** 다섯 개 전부 Variables 탭입니다 — WIF 공급자 경로와
서비스 계정 이메일은 비밀이 아니고, 그것만으로는 아무것도 못 합니다. 실제 통제는
GCP 쪽 조건절이 합니다.

> 워크플로의 `permissions: id-token: write`가 반드시 있어야 합니다. 없으면 OIDC 토큰이
> 발급되지 않아 인증이 실패합니다. `ci-cd.yml`에 이미 들어 있습니다.

### 1-3. VM에 sudo 권한 열기 — **이걸 안 하면 CI가 멈춥니다**

`deploy.sh`는 `sudo systemctl restart planner-api`를 부릅니다. 사람이 돌릴 때는
비밀번호를 입력하면 되지만, **CI는 비대화형이라 거기서 영원히 멈춥니다.**

VM에서:

**sudoers는 명령줄을 문자 그대로 대조합니다.** `deploy.sh`가 실제로 부르는 형태와
글자 하나까지 같아야 하고, 경로도 `which`로 확인한 실제 경로여야 합니다.

`deploy.sh`가 부르는 것은 이 셋입니다.

```
sudo systemctl restart planner-api
sudo systemctl is-active --quiet planner-api      ← --quiet 가 붙는다
sudo journalctl -u planner-api -n 40 --no-pager
```

먼저 실제 경로를 확인합니다(Ubuntu 22.04는 `/usr/bin`입니다).

```bash
which systemctl journalctl
```

그 경로로 규칙을 씁니다.

```bash
sudo tee /etc/sudoers.d/planner-deploy > /dev/null <<'EOF'
planner ALL=(root) NOPASSWD: /usr/bin/systemctl restart planner-api
planner ALL=(root) NOPASSWD: /usr/bin/systemctl is-active --quiet planner-api
planner ALL=(root) NOPASSWD: /usr/bin/journalctl -u planner-api *
EOF
sudo chmod 440 /etc/sudoers.d/planner-deploy
sudo visudo -c          # 문법 검사 — 반드시 통과 확인
```

> 전체 sudo를 주지 않고 **필요한 세 명령만** 엽니다. `planner` 계정이 탈취돼도 할 수
> 있는 일이 이 셋으로 제한됩니다.

**확인 — `-n`(비대화형)을 붙여 시험하는 것이 핵심입니다.** 이게 통과해야 CI에서 멈추지
않습니다. `--quiet`까지 똑같이 넣어 시험하십시오.

```bash
sudo -u planner sudo -n systemctl restart planner-api        && echo "OK 1"
sudo -u planner sudo -n systemctl is-active --quiet planner-api ; echo "OK 2 (종료코드 $?)"
sudo -u planner sudo -n journalctl -u planner-api -n 1 --no-pager > /dev/null && echo "OK 3"
```

`sudo: a password is required`가 나오면 규칙이 실제 명령과 어긋난 것입니다 —
경로(`/usr/bin` vs `/bin`)와 `--quiet` 유무를 다시 대조하십시오.

### 1-4. OS Login 활성화

```bash
gcloud compute instances add-metadata planner-vm \
  --zone=asia-northeast3-a --metadata=enable-oslogin=TRUE
```

## 2. 첫 실행

```bash
git commit --allow-empty -m "ci: 파이프라인 첫 실행"
git push origin main
```

GitHub → **Actions** 탭에서 진행을 봅니다. 손으로 다시 돌리려면 워크플로 화면의
**Run workflow**(`workflow_dispatch`)를 씁니다.

## 3. (폴백) 서비스 계정 키 방식 — 권장하지 않음

WIF 설정이 끝내 안 될 때만 쓰는 우회로입니다. 조직 정책으로 WIF가 막혀 있거나
발표 직전에 시간이 없을 때가 해당합니다.

```bash
gcloud iam service-accounts keys create ~/gh-deployer.json \
  --iam-account="${SA}@${PROJECT_ID}.iam.gserviceaccount.com"
```

`GCP_SA_KEY` **Secret**에 JSON 전체를 넣고, `ci-cd.yml`의 인증 스텝을 이렇게 바꿉니다.

```yaml
      - name: GCP 인증
        uses: google-github-actions/auth@v2
        with:
          credentials_json: ${{ secrets.GCP_SA_KEY }}
```

등록 후 로컬 키 파일을 지웁니다.

```bash
rm ~/gh-deployer.json
```

> **이 키는 만료되지 않습니다.** 유출되면 사람이 폐기할 때까지 계속 유효하고, 키를
> 가진 누구나 어디서든 쓸 수 있습니다(저장소 제한이 없습니다). 이 경로로 갔다면
> 발표 후 WIF로 옮기고 `gcloud iam service-accounts keys delete`로 키를 폐기하십시오.

## 4. 막힐 만한 곳

WIF는 실패 메시지가 불친절합니다. 아래 넷이 거의 전부입니다.

| 증상 | 원인 | 조치 |
|---|---|---|
| `Unable to get the ID token ... id-token: write` | 잡에 `permissions: id-token: write` 없음 | `ci-cd.yml` 확인 (이미 들어 있음) |
| `unable to exchange token ... 403` / `Permission 'iam.serviceAccounts.getAccessToken' denied` | 1-2 ③의 `workloadIdentityUser` 바인딩 누락·오타 | `principalSet` 경로의 프로젝트**번호**(ID 아님)와 저장소명 재확인 |
| `The given credential is rejected by the attribute condition` | 조건절의 저장소명이 실제와 다름 | `assertion.repository`가 `소유자/저장소` 형식인지 확인 |
| `Invalid value for "audience"` | `GCP_WIF_PROVIDER` 값이 잘림 | `projects/<번호>/locations/global/workloadIdentityPools/<풀>/providers/<공급자>` 전체인지 확인 |
| `Permission denied (publickey)` | OS Login 미활성 또는 `roles/compute.osAdminLogin` 누락 | 1-1·1-4 확인 |
| `<user> is not in the sudoers file` | `osLogin`만 부여됨 | `osAdminLogin`으로 교체 (1-1) |
| `Error while connecting [4033: 'not authorized']` | IAP 권한 없음 | `roles/iap.tunnelResourceAccessor` 확인 |
| 배포 단계가 멈춘 채 끝나지 않음 | sudo 비밀번호 대기 | **1-3** 확인 |
| `deploy.sh: DATA_DIR이 설정되지 않았거나` | systemd 유닛에서 `Environment=DATA_DIR` 누락 | 배포 가이드 11절 |
| pytest는 통과인데 배포 후 화면이 깨짐 | 프론트 빌드 산출물 문제 | `SITE_URL/api/health` 응답과 브라우저 콘솔 확인 |

## 5. 한계

- **롤백이 자동이 아닙니다.** 배포가 깨지면 이전 커밋으로 되돌려 다시 push해야 합니다
  (`git revert <sha> && git push`). 무중단 배포나 블루그린은 이번 범위 밖입니다.
- **테스트는 API·저장소 계층만 덮습니다.** 에이전트 12노드와 LLM 프롬프트의 실제 효과는
  검증하지 않습니다 — CI 초록이 "산출물 품질이 좋다"를 뜻하지 않습니다.
- **서비스 계정 키 방식(1-2)은 키가 만료되지 않습니다.** 3절 WIF로 옮기는 편이 낫습니다.
- 배포 중 수십 초간 서비스가 재시작됩니다. 단일 VM·단일 프로세스 구조의 당연한 귀결입니다.
