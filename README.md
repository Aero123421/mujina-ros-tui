# mujina-ros-tui

`mujina_ros` を手元で動かすための補助 TUI です。

公式の `mujina_ros` は `third_party/mujina_ros` に固定 commit で同梱しています。このリポジトリでは、作業用 workspace の作成、依存チェック、CAN/デバイス確認、policy/zero profile の確認、実機起動前のロック条件の表示を TUI から扱えるようにしています。

公式 `mujina_ros` の代替ではありません。実機向けの ROS パッケージ本体は upstream をそのまま持ち、補助ツール側で状態確認と起動手順をまとめます。

## 起動

Ubuntu 24.04 / ROS 2 Jazzy を想定しています。

```bash
git clone https://github.com/Aero123421/mujina-ros-tui.git
cd mujina-ros-tui
./start.sh
```

`./start.sh` は Python 仮想環境を用意して、標準では TUI を起動します。

旧メニューも残しています。

```bash
./start.sh legacy-menu
./start.sh menu --legacy
```

サブコマンドを直接使うこともできます。

```bash
./start.sh doctor
./start.sh build
./start.sh sim
./start.sh policy --test
```

Windows で画面だけ確認する場合は、PowerShell から次のように起動できます。

```powershell
python -m mujina_assist.main tui
```

ROS や実機デバイスがない環境では、TUI 上の各チェックは `WARN` / `LOCK` になります。

## 入っているもの

- `src/mujina_assist`: TUI と補助コマンド
- `third_party/mujina_ros`: 公式 `mujina_ros` の vendored copy
- `patches/mujina_ros`: upstream に対する差分を置く場所
- `workspace`: 生成される ROS workspace
- `tests`: この補助ツール側のテスト

## upstream の扱い

同梱している upstream:

- Repository: `https://github.com/rt-net/mujina_ros`
- Commit: `38ff97f12d0ef424dd7fc840d3ce7a1ebad2a49d`
- License: MIT License
- License file: `third_party/mujina_ros/LICENSE`

`third_party/mujina_ros` は clean copy として扱います。直接編集せず、必要な差分は `patches/mujina_ros/*.patch` か `src/mujina_assist` 側に置きます。

ライセンス表記は `THIRD_PARTY_NOTICES.md` にまとめています。

## workspace mode

- `vanilla`: 同梱した `mujina_ros` をそのまま `workspace/src/mujina_ros` に配置する
- `assisted`: 配置後に `patches/mujina_ros` の patch queue を適用する
- `diagnostic`: 実機にトルクを送る操作を避け、診断を中心に使う

workspace signature は upstream commit、patch set hash、dirty 状態から作ります。signature が変わると、以前の SIM verified は無効として扱います。

## 実機起動のロック

Real launch は、必要な確認が揃うまでロックされます。主な確認項目は次の通りです。

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

このリポジトリの pytest は補助ツール側だけを対象にしています。`third_party/mujina_ros` の ROS / ament 系テストは、ROS 2 Jazzy 環境で別に扱います。

```bash
python -m pytest -q
```

コンテナで確認する場合:

```bash
./scripts/run-docker-tests.sh
```
