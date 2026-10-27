# Contributing — Smart URL Serverless (LinkPulse)

> Quy chế đóng góp bắt buộc cho toàn bộ thành viên (TV1–TV5). Mục tiêu: giữ `main` luôn deploy được,
> mọi thay đổi truy vết được tới Issue, review nhanh gọn, không lộ secret, chi phí AWS trong ngân sách $5/tháng.

---

## 1. Chuẩn bị môi trường (một lần)

```bash
git clone <repo-url> smart-url-serverless-aws && cd smart-url-serverless-aws
aws --version && sam --version          # AWS CLI + SAM CLI (theo docs/backend_research.md §6)
aws configure                           # dùng IAM user riêng do TV5 cấp, KHÔNG dùng root; region ap-southeast-1
                                        # (tài khoản Free-plan kiểu mới bị cố định region theo project — xem backend_research §6.2)
python -m pytest tests -v               # phải PASS trước khi làm việc
```

- Secret (GSB key, Turnstile secret, salt, AWS keys) **không bao giờ** commit — dùng SSM/Secrets Manager + `.env` local (đã có trong `.gitignore`).
- Mọi tài nguyên thử nghiệm deploy bằng SAM phải `sam delete` sau khi xong để khỏi tốn phí.

---

## 2. Git Workflow & quy ước nhánh

- Nhánh chính: `main` (được bảo vệ — chỉ merge qua Pull Request, không push trực tiếp).
- Luồng làm việc: **tạo Issue → tạo branch từ `main` → commit → PR → review ≥1 người → merge (squash)** → xóa branch.
- Đặt tên branch theo mẫu (chữ thường, gạch ngang, có số issue):

| Loại | Mẫu | Ví dụ |
|---|---|---|
| Tính năng | `feature/<issue-id>-<task-name>` | `feature/12-shorten-api` |
| Sửa lỗi | `bugfix/<issue-id>-<task-name>` | `bugfix/31-redirect-loop` |
| Tài liệu | `docs/<issue-id>-<task-name>` | `docs/5-threat-model` |
| Việc kỹ thuật/devops | `chore/<issue-id>-<task-name>` | `chore/5-waf-foundation` |
| Hotfix production | `hotfix/<issue-id>-<task-name>` | `hotfix/44-block-phishing-wave` |

```bash
git checkout main && git pull origin main
git checkout -b feature/12-shorten-api
```

---

## 3. Conventional Commits (bắt buộc — CI kiểm tra)

Định dạng: `<type>(<scope>): <mô tả ngắn imperative, tiếng Việt hoặc Anh, ≤72 ký tự>`

- `type` bắt buộc một trong: `feat` (tính năng mới), `fix` (sửa lỗi), `docs` (tài liệu), `refactor`, `test`, `chore` (build/CI/devops), `perf`, `style`, `ci`, `revert`.
- `scope` khuyến nghị: `shorten`, `redirect`, `stats`, `links`, `waf`, `auth`, `db`, `analytics`, `frontend`, `infra`, `docs`.
- Body (tùy chọn): giải thích *vì sao*, liệt kê `Closes #<id>`; Footer: `Refs #<id>`, `BREAKING CHANGE:` nếu có.

Ví dụ đúng:

```
feat(shorten): thêm validate SSRF chặn IP nội bộ

Kiểm tra IP literal (kể cả dạng 2130706433, 127.1) và resolve DNS,
chặn 10/8, 172.16/12, 192.168/16, 169.254/16.

Closes #5
```

```
fix(redirect): trả no-store cho mọi 302 để đếm click

Refs #1
```

```
docs(security): bổ sung threat model T-06 SSRF

Refs #5
```

Không chấp nhận: `update code`, `fix bug`, `wip`, commit không dấu, commit gộp nhiều việc không liên quan.

---

## 4. Tiêu chuẩn Pull Request

### 4.1. Trước khi mở PR (checklist push)

- [ ] `python -m pytest tests -v` PASS local; thêm test cho logic mới (redirect/validate/threat).
- [ ] Lint/format PASS: `python -m ruff check .` (nếu có) hoặc tối thiểu không lỗi cú pháp; frontend `npx prettier --check`.
- [ ] Không commit secret, file `*.pem`, `.env`, `.aws-sam/`, ảnh > 1 MB chưa nén.
- [ ] Rebase lên `main` mới nhất, giải quyết conflict local (`git pull --rebase origin main`).
- [ ] Một PR = một Issue/một việc; PR > 400 dòng phải tách (dùng skill `/split-to-prs` khi cần).

### 4.2. Mẫu tiêu đề & mô tả PR

- Tiêu đề PR trùng tinh thần commit chính: `feat(shorten): ...` + hậu tố `(Closes #<id>)`.
- Mô tả PR (copy mẫu dưới vào ô description):

```markdown
## Mục tiêu (Closes #id)
<!-- Liên kết Issue: Closes #5 -->

## Thay đổi chính
- ...
- ...

## Kiểm thử
- [ ] `pytest tests -v` PASS (dán số test)
- [ ] Đã thử local / SAM deploy (dán lệnh + kết quả)
- [ ] Ảnh chụp (nếu là UI/architecture): ...

## Ảnh hưởng / rủi ro
- Chi phí AWS thay đổi? (không / +~$x):
- Bảo mật (đi qua checklist SSRF/WAF/Turnstile ở docs/threat_model.md §4?):
- Cần follow-up Issue nào?:

## Checklist
- [ ] Không secret trong diff
- [ ] Đã rebase main, CI xanh
- [ ] Đã gắn reviewer + label (xem §4.3)
```

### 4.3. Label & liên kết Issue

- Mọi PR phải gắn: một label loại (`feature`/`bugfix`/`docs`/`chore`), một label module (`tv1-backend`/`tv2-frontend`/`tv3-database`/`tv4-analytics`/`tv5-security`), và Milestone `Week N` tương ứng.
- Nội dung PR phải chứa `Closes #<id>` (tự đóng Issue khi merge) hoặc `Refs #<id>` (chỉ tham chiếu).

---

## 5. Code Review (quy định bắt buộc)

- Mọi PR cần **≥ 1 approval** của thành viên khác module (ví dụ PR backend cần TV5 hoặc TV2 review). Tác giả không tự approve.
- Reviewer kiểm tra theo thứ tự: **đúng Issue → bảo mật (SSRF/validate/WAF/secret) → hợp đồng `api_spec.yaml` → test → style**.
- Dùng GitHub Suggested Changes cho sửa nhỏ; dùng `Request changes` khi: thiếu test, phá hợp đồng API, có secret, vượt ngưỡng chi phí, logic SSRF/redirect chưa đủ.
- SLA review: phản hồi đầu tiên trong **24h**; PR `hotfix` trong **4h**. Mọi comment phải được resolve hoặc trả lời trước khi merge.
- Merge bằng **Squash and merge** để `main` giữ một commit/PR sạch theo Conventional Commits; xóa branch sau merge.

---

## 6. Quy định kiểm tra trước push (lint/format/test)

```bash
# Backend (Python)
python -m pytest tests -v
python -m ruff check backend analytics tests 2>NUL || python -m py_compile backend/*.py

# API contract: spec phải parse được
python -c "import yaml,sys; yaml.safe_load(open('docs/api_spec.yaml'))" && echo SPEC_OK

# Frontend (nếu sửa JS/CSS)
npx prettier --check "frontend/**/*.{js,css,html}"
```

- CI (GitHub Actions, TV5 dựng Week 2) chạy lại toàn bộ trên + kiểm tra commit message; PR đỏ không được merge.
- Tài liệu Mermaid (`docs/architecture.md`): sửa code Mermaid trước, export lại `docs/architecture.png`, không sửa PNG tay.

---

## 7. An toàn & chi phí (vi phạm là block PR)

1. **Không** hard-code secret/key/salt; chỉ đọc từ env/SSM; không in secret ra log.
2. **Không** mở `0.0.0.0/0` ở Security Group/IAM `*`; IAM theo least-privilege + MFA (xem `scripts/setup_aws_foundation.sh`).
3. Mọi endpoint mới phải có rate-limit + validate tương ứng (`docs/threat_model.md` §4–5).
4. Mọi tài nguyên AWS mới phải có tag `Project=LinkPulse`, ước tính chi phí trong PR, và nằm trong Budget $5/tháng.

---

## 8. Quy trình phát hành & báo sự cố

- Release theo tag `v<major>.<minor>.<patch>` từ `main` sau khi demo tuần PASS; ghi chú release liệt kê Issue đóng.
- Sự cố bảo mật (phishing wave, bill spike): mở Issue `hotfix`, ping TV5, áp dụng kill-switch (WAF block / tắt behavior CloudFront / `status=blocked`), rồi mới viết postmortem trong Issue.

---

*Thắc mắc về quy chế → hỏi trong Issue #5 (TV5) hoặc giờ họp nhóm. Quy chế này được version cùng repo — sửa quy chế cũng phải qua PR.*
