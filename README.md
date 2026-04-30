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

## offline install / wheelhouse

ネットワークが使えない実機へ持ち込む場合は、事前に同じ Python 系列の環境で wheelhouse を作ってから転送します。

```bash
python -m pip wheel -w wheelhouse .
python -m pip wheel -w wheelhouse '.[test]'
```

実機側では repository と `wheelhouse/` を同じ場所に置き、外部 index を使わずにインストールします。

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --no-index --find-links wheelhouse .
```

ROS / apt / rosdep / PyTorch CPU wheel など、OS 側依存はこの wheelhouse だけでは入りません。完全オフライン運用では apt mirror や事前導入済み base image も別途用意してください。

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

各画面の追加キー:

- Setup: `u` で初回セットアップ job、`b` で build job を起動します。TUIの `u` は実機 udev/dialout 設定を含めません。
- CAN: `n` で network CAN setup、`u` で serial CAN setup、`F5` で状態再取得を行います。
- Motor: `n` / `u` で全12軸 read-only query job を network / serial CAN で起動します。値は Logs の job log で確認します。
- Zero: `n` / `u` で zero 前の read-only query を起動できます。原点書き込みは `./start.sh zero` の確認付き CLI に委譲します。
- Policy: `t` で ONNX 読み込みテスト job を起動します。policy 切替は manifest 確認があるため `./start.sh policy` を使います。
- Real Preflight / Real Launch: TUI はロック理由を表示します。実機起動は operator checklist と `REAL` 入力を通すため `./start.sh robot` を使います。

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

### diagnostic mode での許可/禁止

`diagnostic` は「状態確認用」です。TUI / CLI では次の境界で扱います。

許可する操作:

- Doctor / Dashboard / Device / CAN の状態表示
- `preflight` の不足条件表示
- Logs の確認
- workspace の clean copy 作成と signature 確認
- CAN setup 手順の確認、または明示的に選んだ CAN setup job の起動
- read-only / zero-gain の motor query による疎通確認

禁止または確認付き CLI に委譲する操作:

- `zero` による原点書き込み
- `robot` による実機 mujina_main / joy / IMU の段階起動
- standup / walk へ進む操作
- external policy の manifest や SIM verified が未確認のまま実機へ進む操作

TUI 上で `WAIT` / `LOCK` が見えても、それだけで安全が保証されたとは扱いません。実機に進む前は必ず Real Preflight の P0/P1/P2 と CLI 側の確認入力を通してください。

## 配布zip

配布用 zip は作業ディレクトリをOSのzip機能で固めるのではなく、tracked file だけを含める `git archive` を推奨します。

```bash
git archive --format=zip --output mujina-ros-tui.zip HEAD
```

特定タグから作る場合:

```bash
git archive --format=zip --prefix=mujina-ros-tui/ --output mujina-ros-tui-v0.1.0.zip v0.1.0
```

`.state/`、`cache/`、`logs/`、`workspace/`、`.venv/` などの生成物を混ぜないためです。

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
