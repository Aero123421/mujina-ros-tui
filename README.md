# mujina-ros-tui

[![CI](https://github.com/Aero123421/mujina-ros-tui/actions/workflows/ci.yml/badge.svg)](https://github.com/Aero123421/mujina-ros-tui/actions/workflows/ci.yml)

`mujina_ros` をセットアップ、診断、起動前確認までまとめて扱うための日本語 TUI です。

この repository では改行を LF に正規化します。Windows で作業する場合も、この checkout では `git config core.autocrlf false` を推奨します。

公式の `mujina_ros` は `third_party/mujina_ros` に固定 commit で同梱しています。この repository は公式 package の置き換えではなく、作業用 workspace の生成、状態確認、policy / zero profile の確認、実機起動前のロック条件表示をまとめる補助ツールです。

## できること

- 起動直後に workspace / build / policy / device / CAN / motor / zero / SIM / real preflight の状態を確認する
- 同梱した upstream から再現可能な ROS workspace を作る
- `vanilla` / `assisted` / `diagnostic` の workspace mode を扱う
- policy manifest と SIM verification の状態を見えるようにする
- zero profile と post-zero verification を保存、確認する
- 実機起動前に不足している条件を `LOCK` として表示する
- real launch 前に 12 軸 zero-gain query、`/imu/data`、`/robot_mode`、`/joy` の live health を段階確認する
- 長い処理や常駐プロセスを job として管理し、ログを追う

## 想定環境

- Ubuntu 24.04
- ROS 2 Jazzy
- Python 3.10 以上

Windows でも TUI の画面確認や Python 側のテストはできます。ROS / CAN / 実機デバイスを使う操作は Ubuntu 環境を前提にしています。

## 起動

```bash
git clone https://github.com/Aero123421/mujina-ros-tui.git
cd mujina-ros-tui
./start.sh
```

`./start.sh` は `.venv` を用意して、標準では TUI を起動します。

旧メニューを開く場合:

```bash
./start.sh legacy-menu
./start.sh menu --legacy
```

サブコマンドを直接実行する場合:

```bash
./start.sh doctor
./start.sh build
./start.sh sim
./start.sh policy --test
```

Windows PowerShell で画面だけ確認する場合:

```powershell
python -m mujina_assist.main tui
```

ROS や実機デバイスがない環境では、TUI 上の各チェックは `WARN` / `LOCK` として表示されます。

## キー操作

TUI では下部 footer の keybind から各画面へ移動します。

| Key | Screen |
| --- | --- |
| `d` | Doctor |
| `s` | Setup |
| `p` | Policy |
| `m` | Motor |
| `z` | Zero |
| `c` | CAN |
| `i` | Device |
| `r` | Real |
| `l` | Logs |
| `?` | Help |
| `q` | Quit |

## Repository 構成

```text
mujina-ros-tui/
├── .github/
│   └── workflows/
│       └── ci.yml
├── docs/
│   ├── architecture.md
│   ├── review-2026-03-22.md
│   └── virtualbox-test.md
├── patches/
│   └── mujina_ros/
├── scripts/
│   ├── run-container-tests.sh
│   └── run-docker-tests.sh
├── src/
│   └── mujina_assist/
│       ├── app.py
│       ├── main.py
│       ├── models.py
│       ├── services/
│       └── tui/
├── tests/
├── third_party/
│   ├── mujina_ros/
│   └── mujina_ros.upstream.json
├── Dockerfile.test
├── LICENSE
├── pyproject.toml
├── README.md
├── start.sh
└── THIRD_PARTY_NOTICES.md
```

主な場所:

- `src/mujina_assist`: TUI と補助コマンド本体
- `src/mujina_assist/services`: workspace、CAN、device、policy、zero、safety などの処理
- `src/mujina_assist/tui`: Textual ベースの TUI 画面
- `third_party/mujina_ros`: 公式 `mujina_ros` の vendored copy
- `patches/mujina_ros`: upstream に対する patch queue
- `tests`: この補助ツール側のテスト

実行時には `.state/`、`cache/`、`logs/`、`workspace/` が作られます。これらは生成物です。

## upstream の扱い

同梱している upstream:

- Repository: `https://github.com/rt-net/mujina_ros`
- Commit: `38ff97f12d0ef424dd7fc840d3ce7a1ebad2a49d`
- License: MIT License
- License file: `third_party/mujina_ros/LICENSE`

`third_party/mujina_ros` は clean copy として扱います。直接編集せず、必要な差分は `patches/mujina_ros/*.patch` か `src/mujina_assist` 側に置きます。

サードパーティ表記は `THIRD_PARTY_NOTICES.md` にまとめています。

現在の patch queue には CAN setup、IMU driver、motor response handling、`mujina_main` safety guard の補正を置いています。`third_party/mujina_ros` は直接編集せず、`workspace/src/mujina_ros` 作成時に適用します。

## workspace mode

| Mode | 内容 |
| --- | --- |
| `vanilla` | 同梱した `mujina_ros` をそのまま `workspace/src/mujina_ros` に配置する |
| `assisted` | 配置後に `patches/mujina_ros` の patch queue を適用する |
| `diagnostic` | 同梱 upstream を clean copy として配置し、実機にトルクを送る操作を避ける診断用 workspace として記録する |

workspace signature は upstream commit、mode、patch set hash、workspace tree hash、dirty 状態から作ります。signature が変わると、以前の SIM verified は無効として扱います。

## 実機起動のロック

Real launch は、必要な確認が揃うまでロックされます。

- workspace が build 済み
- active policy の出所が分かる
- external policy に manifest がある
- 現在の policy と workspace signature で SIM verified 済み
- CAN / IMU / gamepad が確認できる
- zero profile が verified
- operator checklist と `REAL` confirmation が完了している
- manual recovery が未解決ではない

ロック状態は TUI の dashboard と preflight 画面で確認します。

## テスト

ローカルで実行:

```bash
python -m pytest -q
```

コンテナで実行:

```bash
./scripts/run-docker-tests.sh
```

GitHub Actions では push と pull request ごとに `python -m pytest -q` を実行します。

## License

この repository 本体は MIT License です。ルートの `LICENSE` を参照してください。

同梱している公式 `mujina_ros` も MIT License です。upstream の copyright と license は `third_party/mujina_ros/LICENSE` に残してあり、`THIRD_PARTY_NOTICES.md` にも記載しています。
