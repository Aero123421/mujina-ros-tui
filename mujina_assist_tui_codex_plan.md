# Mujina Assist TUI 改修計画・TODO・Codex指示書

作成日: 2026-04-29  
対象: `omujina-ros-CLI` / `mujina_ros` wrapper project  
目的: コマンドベースの便利CLIではなく、Mujina実機のセットアップ・診断・policy切替・zero position・SIM確認・実機起動までを、流れるように扱えるリッチなターミナルアプリにする。

---

## 0. 結論

このプロジェクトは、`mujina_ros` を置き換えるプロジェクトではなく、**公式 `mujina_ros` の安全な運用ラッパー** として作る。  
ただし、公式側に明らかな実機運用上の粗さや不整合があるため、公式リポジトリを直接改変するのではなく、以下の形でこのリポジトリ内に取り込む。

推奨構成は次のどちらか。

1. **patch queue方式**
   - 実行時に公式 `mujina_ros` を clone する。
   - `patches/mujina_ros/*.patch` をワークスペース内のcloneへ適用する。
   - upstream commit、patch適用状態、dirty状態をTUIで見えるようにする。
   - 「vanilla upstream」と「assisted patched」の差分をユーザーが理解できる。

2. **vendored upstream + patch方式**
   - `third_party/mujina_ros` に公式の特定commitを内包する。
   - `third_party/mujina_ros` は原則clean mirrorとして扱う。
   - 実際に改修したい内容は `patches/mujina_ros` または `overlays/mujina_ros` として管理する。
   - setup時に `workspace/src/mujina_ros` へ clean copy し、必要なpatchを適用する。

**おすすめは 2 の vendored upstream + patch方式。**  
理由は、実機ロボットのセットアップツールでは「今日GitHubから落とした最新版」より「このバージョンで動作確認した」という固定性が重要だから。

ただし、公式の動作を壊さないため、必ず次のモードを分ける。

- `Vanilla mode`: 公式 `mujina_ros` をそのまま使う。
- `Assisted mode`: このツールが安全運用のためのpatchやwrapperを適用して使う。
- `Diagnostic only`: 実機にトルクを送らず、状態確認だけ行う。

---

## 1. 今のCLIの評価

現在の `omujina-ros-CLI` は、方向性としては良い。

良い点:

- 公式 `mujina_ros` の clone、build、SIM、実機起動、policy切替をまとめようとしている。
- state管理がある。
- job管理がある。
- policy cache / default policy backup / rollbackの考え方がある。
- 実機起動前にpolicy provenanceやSIM確認を要求している。
- zero position や motor read を実機起動と分離している。
- workerを別ターミナルまたはtmuxで起動する設計がある。

しかし、ユーザー体験としてはまだ「リッチなアプリ」ではない。

問題点:

- 画面が番号メニュー中心で、常に状態が見えるTUIではない。
- device / CAN / IMU / joy / motor / policy / job / log が1画面にまとまっていない。
- setupから実機起動までの進行状態が「wizard」として見えない。
- ROS topicのライブヘルスチェックが弱い。
- CAN状態の読み取りがまだ浅い。
- motor scan結果が関節名・ID・温度・エラー・zero状態として整理されていない。
- zero position後の検証とzero profile保存がない。
- policy manifest検証が弱い。
- 実機起動がまだ「IMU/main/joyをまとめて起動」に近く、段階起動・段階unlockではない。
- 別ターミナル起動は便利だが、ユーザーが「いま何が起きているか」をメイン画面から追いにくい。

目指す状態は、`./start.sh` または `mujina-assist` を実行すると、すぐにフルスクリーンTUIが立ち上がり、キーボードだけでセットアップから実機起動まで流れること。

---

## 2. 公式 `mujina_ros` 側の前提と注意点

公式README上の前提:

- Ubuntu Desktop 24.04
- ROS 2 Jazzy
- Mujina hardware
- Logicool F710 / F310 推奨
- candleLight_fw対応USB-CAN推奨
- 初回使用前にmotor origin設定が必要
- 実機起動はIMU、`mujina_main`、`joy_linux_node` を別ターミナルで起動する流れ
- SIMでは `ros2 run mujina_control mujina_main --sim`
- serial CAN では `can_setup_serial.sh`

ローカルに展開した公式ZIPから見える重要点:

- `mujina_control/scripts/can_setup_net.sh` は `can0` を 1Mbps でupするだけに近い。
- `mujina_control/scripts/can_setup_serial.sh` は `slcand` 起動と `can0` upだけに近い。
- `motor_set_zero_position.py` は `CanMotorController.set_zero_position()` を呼ぶだけで、事前姿勢確認、静止確認、post verification、zero profile保存がない。
- `mujina_main.py` は `CanCommunicationNode` の初期化時に12軸enableし、`TRANSITION_TO_STANDBY` に入る。
- `CanCommunicationNode.timer_callback()` では各motorへ `send_rad_command()` を送り、例外時にerror countを増やし、5回でemergency stopにする。
- `mujina_main.py` の `joy_callback()` は `msg.axes[1]`, `msg.axes[0]`, `msg.axes[3]`, `msg.buttons[0..2]` を直接読む。gamepad未接続やmapping不一致時に落ち得る。
- `mode_transition_command_callback()` は `msg.mode` 文字列と `RobotModeCommand` Enumの比較が怪しい。外部からmode commandを送るwrapper設計では注意が必要。
- `rt_usb_imu_driver/README.md` は `qx,qy,qz,qw,gx,gy,gz\n` の7値、2000000bps想定と読める。
- しかし `rt_usb_imu_driver/src/parser.cpp` は8値を要求しており、`rt_usb_imu_driver.cpp` は `latest_data[1]..[7]` を使う。
- `rt_usb_imu_driver.cpp` は `B38400` を設定しており、README記載の2000000bpsと不一致に見える。
- `port_fd_` の扱いが `if (port_fd_)` で、`-1` も真になるため、open失敗時の挙動が危ない。

CLI/TUI側で補うべきこと:

- upstreamを勝手に壊さない。
- でも実機安全のために、公式手順の前後にpreflight、診断、記録、段階unlockを入れる。
- 公式ノードそのものを改造せずに済むところは、wrapperからtopic監視・process監視・ログ監視で補う。
- 改修が必要なところはpatchとして明示する。

---

## 3. `mujina_ros` をこのリポジトリに内包して改修して良いか

答え: **良い。ただし「公式を勝手に改変したもの」と「公式そのもの」を混ぜないこと。**

やるべき管理:

```text
third_party/
  mujina_ros/
    # 公式の特定commitをcleanに保持する
    # README, LICENSE, commit metadata を保持

patches/
  mujina_ros/
    0001-can-setup-harden.patch
    0002-imu-driver-format-and-baud.patch
    0003-mujina-main-safety-wrapper.patch

src/mujina_assist/
  tui/
  services/
  ros/
  devices/
  safety/
  policy/
  zero/

overlays/
  mujina_ros/
    # patchより大きい差し替えが必要な場合だけ
```

原則:

- `third_party/mujina_ros` はclean upstreamとして保持する。
- 実際に動かすworkspaceは `workspace/src/mujina_ros`。
- `workspace/src/mujina_ros` はsetup時に生成される作業コピー。
- patch適用後はTUIに `patched` と表示する。
- `mujina_ros` のMIT licenseとcopyrightを必ず保持する。
- `README.md` に「このツールは公式 `mujina_ros` の安全運用支援ラッパーであり、公式プロジェクトそのものではない」と明記する。
- 公式挙動を壊さないため、`vanilla launch` と `assisted launch` を分ける。

おすすめの判断:

- CAN setup script強化、IMU driver修正、mujina_mainの安全修正などはpatch queueにする。
- TUI、診断、zero profile、policy manager、preflightはこのリポジトリ側の独立機能にする。
- 公式コードを直接importして内部API依存するのは最小限にする。なるべくCLIから公式script/ROS nodeを呼ぶ。

---

## 4. 目指すTUIの完成像

起動後の画面イメージ:

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Mujina Assist TUI                                           v0.3.0  patched │
├──────────────────────────────────────────────────────────────────────────────┤
│ Workspace  OK    mujina_ros @ 38ff97f + 3 patches                            │
│ Build      OK    last build 2026-04-29 13:10                                 │
│ Policy     OK    official default  sha256=ab12...  SIM verified              │
│ Devices    WARN  IMU OK / CAN OK / Joy missing                               │
│ CAN        OK    can0 UP 1Mbps ERROR-ACTIVE rx=1204 tx=1202 err=0            │
│ IMU        OK    /imu/data 198.7Hz  quat_norm=0.9998  age=0.006s             │
│ Motors     OK    12/12 responded  max_temp=34.1C                             │
│ Zero       OK    profile: 2026-04-29 12:42  verified                         │
│ Safety     LOCK  Joy missing; operator checklist incomplete                  │
├─────────────────────────────┬────────────────────────────────────────────────┤
│ Flow                        │ Detail                                         │
│ ✓ System                    │ 何がOK/NGか、次に何を押せば良いか             │
│ ✓ Workspace                 │                                                │
│ ✓ Build                     │                                                │
│ ✓ Devices                   │                                                │
│ ✓ Motor Scan                │                                                │
│ ✓ Zero Wizard               │                                                │
│ ✓ Simulation                │                                                │
│ → Real Preflight            │                                                │
│   Real Launch               │                                                │
├─────────────────────────────┴────────────────────────────────────────────────┤
│ [↑↓] Move  [Enter] Open  [d] Doctor  [z] Zero  [p] Policy  [r] Real  [?] Help │
└──────────────────────────────────────────────────────────────────────────────┘
```

方針:

- ユーザーにコマンドを覚えさせない。
- ただしテスト・自動化用のsubcommandは残す。
- 通常入口は `./start.sh` → TUI。
- 画面遷移はキーボード中心。
- setup中の長い処理も同じTUI内のlog paneで見える。
- 実機起動の安全criticalな処理は、画面上の状態がOKになるまでunlockしない。

---

## 5. 技術選定

### 第一候補: Textual

理由:

- Python製なので現在のCLI資産を活かせる。
- フルスクリーンTUI、キーバインド、panel、table、log view、progress、async workerに向いている。
- 既存のservice層を分離すれば、UIだけTextualへ移行できる。
- SSH上でも使いやすい。
- `rich` と相性が良い。

追加依存案:

```toml
[project]
dependencies = [
  "textual>=0.80",
  "rich>=13",
  "typing-extensions>=4.10",
]
```

バージョンは実装時に確認して固定する。実機運用ではむやみにfloatingにしない。

### 第二候補: prompt_toolkit

- 軽量でフルスクリーンアプリも作れる。
- ただし画面構成やログ・表・複数paneはTextualの方が実装しやすい。

### 非推奨

- 今の `input()` ベースを豪華にするだけ。
- curses直書き。
- `urwid` などで新規に重い設計をする。

---

## 6. TUI画面構成

### 6.1 DashboardScreen

常に見るメイン画面。

表示:

- System: OS / ROS / Python / venv
- Workspace: upstream commit / patched / dirty / build status
- Devices: `/dev/rt_usb_imu`, `/dev/usb_can`, `can0`, `/dev/input/js0`
- CAN: state, bitrate, restart-ms, rx/tx/errors, bus-off
- IMU: topic, rate, last age, quat norm, gyro sanity
- Motors: 12/12 response, temperatures, error codes
- Zero: zero profile status
- Policy: active label, hash, source, manifest, SIM verified
- Jobs: running/stopped/failed
- Logs: recent error summary
- Safety: launch lock reason

操作:

- `Enter`: 選択中カードの詳細へ
- `d`: Doctor
- `s`: Setup Flow
- `p`: Policy
- `m`: Motors
- `z`: Zero Wizard
- `c`: CAN
- `i`: IMU
- `r`: Real Preflight
- `l`: Logs
- `?`: Help
- `q`: 終了確認

### 6.2 SetupFlowScreen

初回セットアップを流れるように行う画面。

ステップ:

1. OS確認
2. ROS 2 Jazzy確認
3. apt依存確認
4. workspace準備
5. upstream準備
6. patch適用状態確認
7. rosdep
8. Python依存
9. colcon build
10. udev rule
11. dialout group
12. 再ログイン必要判定
13. device確認
14. SIM準備

画面では各ステップに `PENDING / RUNNING / OK / WARN / NG` を表示する。

### 6.3 DeviceScreen

目的:

- 実機接続の見える化。
- udev問題を切り分ける。

表示:

```text
Devices
  IMU fixed symlink       /dev/rt_usb_imu     OK
  USB CAN fixed symlink   /dev/usb_can        OK
  SocketCAN interface     can0                UP
  Gamepad                 /dev/input/js0      Missing

Serial candidates
  /dev/ttyUSB0  vendor=... product=... by-id=...
  /dev/ttyACM0  vendor=... product=... by-id=...
```

注意:

- `/dev/ttyUSB0` が一個だけあるからIMU扱い、という自動fallbackは危険。
- TUI上ではfallback候補として表示するだけにする。
- 実機起動では固定名 `/dev/rt_usb_imu` を原則必須にする。
- fallbackを使う場合は明示unlockが必要。

### 6.4 CANScreen

目的:

- CANの状態確認、setup、reset、dump、stats。

表示:

- interface exists
- operstate
- CAN controller state
- bitrate
- restart-ms
- txqueuelen
- rx packets
- tx packets
- rx errors
- tx errors
- bus errors
- bus-off
- slcand process
- `/dev/usb_can`

操作:

- `n`: network CAN setup
- `s`: serial CAN setup
- `r`: reset can0
- `d`: candump 5秒
- `t`: stats更新

CLI内部実装では、公式scriptをそのまま呼ぶモードと、assisted setup scriptを呼ぶモードを分ける。

### 6.5 MotorScreen

目的:

- 12軸の状態を表形式で見る。
- passive read / one-shot scanをする。

表示:

```text
Joint              ID  Resp  Pos(rad)  Vel(rad/s)  Temp(C)  Err  Zero
RL_collar_joint    10  OK    -0.003    0.000       32.1     0x00 OK
RL_hip_joint       11  OK     0.002    0.001       31.9     0x00 OK
RL_knee_joint      12  OK     0.011    0.000       33.0     0x00 OK
...
FR_knee_joint       3  TIMEOUT
```

操作:

- `a`: all motor scan
- `1..4`: leg別表示
- `p`: passive read loop
- `z`: zero wizardへ
- `e`: error details

注意:

- passive readは「トルクを出していない」と明示する。
- 公式 `motor_test_read_only.py` は実際には `send_rad_command(0,0,0,0,0)` を使っているので、名称だけで完全安全と決めつけない。
- assisted diagnosticでは、可能ならCANフレームの種類と応答IDを検証する独自probeを作る。

### 6.6 ZeroWizardScreen

目的:

- zero positionを失敗しにくくする。
- zero設定を記録・検証する。

ステップ:

1. `mujina_ros` 公式姿勢画像/説明を表示する。
2. CAN状態確認。
3. 対象motor選択。
4. passive scan。
5. 静止確認。
6. operator checklist。
7. confirmation phrase。
8. 公式 `motor_set_zero_position.py` 実行。
9. post-zero scan。
10. zero profile保存。
11. 実機起動unlock条件を更新。

zero profile例:

```json
{
  "schema_version": 1,
  "created_at": "2026-04-29T12:42:00+09:00",
  "upstream_commit": "38ff97f12d0ef424dd7fc840d3ce7a1ebad2a49d",
  "patch_set_hash": "...",
  "can_interface": "can0",
  "motor_ids": [10,11,12,7,8,9,4,5,6,1,2,3],
  "joint_order": [
    "RL_collar_joint", "RL_hip_joint", "RL_knee_joint",
    "RR_collar_joint", "RR_hip_joint", "RR_knee_joint",
    "FL_collar_joint", "FL_hip_joint", "FL_knee_joint",
    "FR_collar_joint", "FR_hip_joint", "FR_knee_joint"
  ],
  "result": "verified",
  "operator_confirmed": true,
  "post_zero_max_abs_position_rad": 0.02
}
```

zero wizardのブロック条件:

- can0がない。
- CAN stateがbus-off/error-passive。
- 対象motorが応答しない。
- velocityが閾値以上。
- real_mainが動作中。
- motor_readが動作中。
- user confirmationが未完了。

### 6.7 PolicyScreen

目的:

- policy切替を安心して行う。
- default policy、cache policy、USB policy、manual path policyを一覧化。
- 実機使用できるかどうかを表示する。

表示:

```text
Policy list
  official default      active  SIM verified  real OK
  usb/policy-a.onnx             not verified  real blocked: no manifest
  cache/walk-v2.onnx            SIM verified  real blocked: robot revision mismatch
```

policy manifest例:

```json
{
  "schema_version": 1,
  "robot": "mujina",
  "robot_revision": "unknown-or-v1",
  "framework": "onnx",
  "input": {
    "shape": [1, 45],
    "observation_order": [
      "base_ang_vel_3",
      "projected_gravity_3",
      "command_3",
      "dof_pos_minus_default_12",
      "dof_vel_12",
      "last_actions_12"
    ]
  },
  "output": {
    "shape": [1, 12],
    "unit": "action",
    "scale": 0.25,
    "target_formula": "ref_angle = action * action_scale + DEFAULT_ANGLE"
  },
  "joint_order": [
    "RL_collar_joint", "RL_hip_joint", "RL_knee_joint",
    "RR_collar_joint", "RR_hip_joint", "RR_knee_joint",
    "FL_collar_joint", "FL_hip_joint", "FL_knee_joint",
    "FR_collar_joint", "FR_hip_joint", "FR_knee_joint"
  ],
  "hash": {
    "onnx_sha256": "..."
  },
  "safety": {
    "requires_sim_verification": true,
    "real_world_approved": false
  }
}
```

切替フロー:

1. 候補選択。
2. ONNX読み込み。
3. input/output shape確認。
4. manifest確認。
5. default backup確認。
6. `mujina_control/models/policy.onnx` へ反映。
7. 必要に応じてbuild。
8. `python3 -m mujina_control.mujina_utils.mujina_onnx` 実行。
9. stateにactive policy hash保存。
10. SIM verificationをリセット。

実機unlock条件:

- default policyならreal OK。ただしSIM確認は推奨または必須にする。
- external policyならmanifest必須。
- external policyはSIM verified必須。
- input shapeは `[1,45]`。
- output shapeは `[1,12]`。
- joint orderがMujina側と一致。
- hashがstateに記録されている。

### 6.8 SimulationScreen

目的:

- policy変更後、実機前にSIM確認を必ず行う。

機能:

- SIM起動。
- joy node起動。
- `/robot_mode`, `/motor_state`, `/joint_states`, `/motor_log` のtopic確認。
- active policy hashとworkspace signatureをsessionに紐付ける。
- ユーザーが姿勢と入力応答を確認したら `SIM verified` を付与。

ブロック条件:

- SIMが起動していない状態で `SIM verified` を押せない。
- active policy hashが変わったらSIM verifiedを剥がす。
- upstream commit/patch hashが変わったらSIM verifiedを剥がす。

### 6.9 RealPreflightScreen

目的:

- 実機起動の全条件を1画面で確認。

チェック:

```text
Real Preflight
  Workspace      OK
  Build          OK
  Patch state    OK assisted patches applied
  Policy         OK official default / SIM verified
  Udev           OK
  CAN            OK can0 ERROR-ACTIVE
  IMU device     OK /dev/rt_usb_imu
  IMU topic      OK /imu/data 198Hz
  Joy device     OK /dev/input/js0
  Joy topic      OK /joy 50Hz axes=6 buttons=11
  Motors         OK 12/12 responded
  Zero profile   OK verified
  Logs           OK no recent fatal errors
  Operator       WAIT checklist
```

unlock条件:

- 全P0項目OK。
- operator checklist完了。
- `REAL` confirmation入力。

### 6.10 RealLaunchScreen

目的:

- 実機を段階起動する。

段階:

1. CAN setup
2. IMU node start
3. wait `/imu/data`
4. IMU sanity check
5. passive motor scan
6. zero profile check
7. `mujina_main` start
8. wait `/robot_mode`
9. wait `/motor_state`
10. joy node start
11. wait `/joy`
12. standby確認
13. standup unlock

重要:

- いきなりIMU/main/joyを全部起動しない。
- 各段階のOK/NGを画面で見せる。
- 失敗したらrollback/stopを画面に出す。
- stop allを常に押せるようにする。

---

## 7. State Machine

TUI全体の状態は、画面ごとにバラバラに持たず、単一のruntime stateに集約する。

### 7.1 Runtime state案

```python
@dataclass
class RuntimeState:
    app_version: str
    workspace: WorkspaceState
    patch_state: PatchState
    system: SystemState
    devices: DeviceState
    can: CanState
    imu: ImuState
    joy: JoyState
    motors: MotorStateSummary
    zero: ZeroState
    policy: PolicyState
    sim: SimState
    real: RealState
    jobs: JobSummary
    safety: SafetyState
```

### 7.2 SafetyState案

```python
@dataclass
class SafetyState:
    real_launch_locked: bool
    lock_reasons: list[str]
    standup_locked: bool
    walk_locked: bool
    emergency_stop_required: bool
    manual_recovery_required: bool
    manual_recovery_summary: str
```

### 7.3 安全判定の優先順位

P0: 絶対に実機起動不可

- build未完了
- active policy不明
- external policyでmanifestなし
- SIM未確認
- CAN bus-off / error-passive
- IMU device未検出
- IMU topic未publish
- 12モータscan失敗
- zero profileなし
- real_mainが既に起動中
- 前回のmanual recoveryが未解決

P1: 実機起動は止めるべき

- joy未検出
- can error counter増加中
- IMU quaternion norm異常
- motor温度高め
- workspace dirty
- patch適用状態不明

P2: 警告のみ

- USBシリアル候補はあるが固定symlinkなし
- tmuxなし
- GUI terminalなし
- logsが多い

---

## 8. `mujina_ros` へのpatch候補

公式を直接改修できない場合、このリポジトリ内でpatchとして保持する。

### 8.1 P0 patch: IMU driver整合

目的:

- READMEと実装のformat/baudrate不一致を解消。

内容:

- `baud_rate` parameter追加。defaultはREADMEに合わせて `2000000`、または現在実機に合わせて設定可能にする。
- parserは7値と8値のどちらを受けるか仕様化。
- `qx,qy,qz,qw,gx,gy,gz` なら index `[0..6]` を使う。
- `timestamp,qx,qy,qz,qw,gx,gy,gz` なら index `[1..7]` を使う。
- parse errorはrate-limit logging。
- `std::cout` 連打をやめる。
- `port_fd_ = -1` 初期化。
- `port_fd_ >= 0` で判定。
- open失敗時にtimer開始しない。
- `tcgetattr()` または `termios term{}` で初期化。
- quaternion normが異常ならwarn。

### 8.2 P0 patch: CAN setup hardening

目的:

- bus-off復帰、重複slcand、txqueuelen、状態表示を追加。

`can_setup_net.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

IFACE="${1:-can0}"
BITRATE="${BITRATE:-1000000}"
RESTART_MS="${RESTART_MS:-100}"
TX_QUEUE_LEN="${TX_QUEUE_LEN:-1000}"

sudo ip link set "$IFACE" down 2>/dev/null || true
sudo ip link set "$IFACE" type can bitrate "$BITRATE" restart-ms "$RESTART_MS"
sudo ip link set "$IFACE" txqueuelen "$TX_QUEUE_LEN"
sudo ip link set "$IFACE" up
ip -details -statistics link show "$IFACE"
```

`can_setup_serial.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

DEV="${1:-/dev/usb_can}"
IFACE="${2:-can0}"
SPEED="${SLCAN_SPEED:--s8}"
TX_QUEUE_LEN="${TX_QUEUE_LEN:-1000}"

test -e "$DEV" || { echo "device missing: $DEV" >&2; exit 2; }
sudo ip link set "$IFACE" down 2>/dev/null || true
sudo pkill -f "slcand.*$DEV.*$IFACE" 2>/dev/null || true
sudo slcand -o -c "$SPEED" "$DEV" "$IFACE"
sudo ip link set "$IFACE" txqueuelen "$TX_QUEUE_LEN"
sudo ip link set "$IFACE" up
ip -details -statistics link show "$IFACE"
```

### 8.3 P1 patch: `mujina_main.py` safety polish

内容:

- `robot_state.velocity/current/temperature` の初期値を `STANDBY_ANGLE` ではなく0または妥当値にする。
- `JointState` と `MotorLog` のheader stampを実時刻にする。
- `joy_callback()` にaxes/buttons長チェックを入れる。
- button edge detectionを入れる。
- `mode_transition_command_callback()` で `RobotModeCommand(msg.mode)` のように文字列からEnumへ変換する。
- CAN成功時は該当motorのerror_countをresetする。
- joint targetは常にURDF limitでclampする。
- safety eventをログに構造化して出す。

### 8.4 P1 patch: motor_lib応答検証

内容:

- `_recv_can_frame()` が受けたCAN frameのmotor id / command type / DLCを検証する。
- timeoutは`None`ではなくtyped exceptionにする。
- unexpected frameは捨てずに一定時間matching responseを待つ。
- RobStride error_code/patternを返却し、ログに出す。
- `data_frame(4)` のような怪しい箇所を修正する。
- busy waitを必要最小限にする。

### 8.5 P2 patch: SIM path修正

内容:

- `src/mujina_ros/mujina_control/models/scene.xml` という相対パス固定をやめる。
- `get_package_share_directory('mujina_control')` で取得する。

---

## 9. TUI実装TODO

### Phase 0: 整理

- [ ] `.pytest_cache`, `__pycache__`, `*.pyc` を削除。
- [ ] `.gitignore` を整理。
- [ ] `README.md` をTUI前提に更新。
- [ ] 現在の `app.py` を分割する。
- [ ] service層はUI非依存にする。
- [ ] subcommandはテスト・緊急用に残す。

### Phase 1: Textual導入

- [ ] `pyproject.toml` に `textual`, `rich` を追加。
- [ ] `src/mujina_assist/tui/app.py` を作る。
- [ ] `./start.sh` のdefaultをTUI起動にする。
- [ ] `--legacy-menu` で旧番号メニューを残す。
- [ ] `mujina-assist doctor --json` のような機械可読出力を残す。
- [ ] DashboardScreenを作る。
- [ ] 基本keybindを実装する。

### Phase 2: State / Watcher

- [ ] `RuntimeState` を拡張。
- [ ] `StateStore` を作る。
- [ ] atomic write / corrupt quarantineは既存資産を流用。
- [ ] `StatusAggregator` を作る。
- [ ] 1秒周期でsystem/device/job/logを更新。
- [ ] ROS topic watcherはROS環境がある時だけ有効。
- [ ] can watcherを作る。
- [ ] imu topic watcherを作る。
- [ ] joy topic watcherを作る。

### Phase 3: Setup Wizard

- [ ] SetupFlowScreenを作る。
- [ ] step modelを作る。
- [ ] apt/rosdep/buildのprogress/log paneを表示。
- [ ] jobをTUI内で起動・停止できるようにする。
- [ ] sudoが必要な処理は明確に表示。
- [ ] 再ログイン必要性をTUIに表示。

### Phase 4: Workspace / upstream管理

- [ ] `third_party/mujina_ros` を使うか、clone方式かを決定。
- [ ] `WorkspaceManager` を作る。
- [ ] upstream commitを保存。
- [ ] patch set hashを保存。
- [ ] vanilla/assisted modeを切り替え可能にする。
- [ ] workspace dirtyを検出。
- [ ] patch適用失敗時のrollbackを実装。

### Phase 5: Device / CAN

- [ ] `DeviceScreen` を作る。
- [ ] udev symlink確認。
- [ ] `udevadm info` からVID/PID表示。
- [ ] `/dev/ttyUSB*`, `/dev/ttyACM*`, `/dev/serial/by-id/*` を候補表示。
- [ ] `CANScreen` を作る。
- [ ] `ip -details -statistics link show can0` parserを強化。
- [ ] bitrate, restart-ms, state, errorsを取る。
- [ ] slcand process検出。
- [ ] `can setup net/serial/reset/dump/stats` をTUI action化。

### Phase 6: Motor scan

- [ ] `MotorScreen` を作る。
- [ ] joint name / motor id / direction / gear ratioを公式parametersから読むか定数化。
- [ ] all 12 scanを表表示。
- [ ] timeout / unexpected / error_code を表示。
- [ ] motor温度警告。
- [ ] passive read loopをTUI内に表示。
- [ ] 実機起動中はmotor operationをlock。

### Phase 7: Zero wizard

- [ ] `ZeroWizardScreen` を作る。
- [ ] 対象選択: all / leg / motor。
- [ ] 公式姿勢説明を表示。
- [ ] passive scan。
- [ ] 静止確認。
- [ ] confirmation phrase。
- [ ] 公式script実行。
- [ ] post-zero scan。
- [ ] zero profile保存。
- [ ] zero profileが古い/commit違い/patch違いならwarn。

### Phase 8: Policy manager

- [ ] `PolicyScreen` を作る。
- [ ] default policy backup。
- [ ] USB policy scan。
- [ ] cache policy list。
- [ ] ONNX metadata inspection。
- [ ] shape check `[1,45] -> [1,12]`。
- [ ] manifest schema定義。
- [ ] manifest validation。
- [ ] switch rollback。
- [ ] switch後はSIM verifiedをreset。
- [ ] active policy stateをTUIに常時表示。

### Phase 9: SIM

- [ ] `SimulationScreen` を作る。
- [ ] sim main / joy nodeをjob groupとして起動。
- [ ] `/robot_mode`, `/motor_state`, `/joint_states`, `/motor_log`, `/joy` を監視。
- [ ] active policy hash + workspace signatureをsessionに紐付け。
- [ ] SIM確認済み付与。

### Phase 10: Real preflight / launch

- [ ] `RealPreflightScreen` を作る。
- [ ] P0/P1/P2 lock reasonを表示。
- [ ] operator checklist。
- [ ] `REAL` confirmation。
- [ ] `RealLaunchScreen` を作る。
- [ ] 段階起動。
- [ ] IMU node起動後にtopic確認。
- [ ] CAN setup後にstate確認。
- [ ] passive motor scan後にmain起動。
- [ ] joy topic確認。
- [ ] stop allを常時表示。
- [ ] 起動失敗時rollback。

### Phase 11: Logs / recovery

- [ ] `LogScreen` を作る。
- [ ] job log tail。
- [ ] error summary。
- [ ] manual recovery state表示。
- [ ] `Stop all` 実装。
- [ ] tmux session kill。
- [ ] process group kill。
- [ ] ROS node残存確認。

### Phase 12: Tests

- [ ] Textual app smoke test。
- [ ] keybind smoke test。
- [ ] state serialization test。
- [ ] can parser test。
- [ ] udev/serial parser test。
- [ ] policy manifest test。
- [ ] zero profile test。
- [ ] preflight gating test。
- [ ] job rollback test。
- [ ] no `__pycache__` / no `.pytest_cache` in repo test。

---

## 10. Codexへ渡すメイン指示Prompt

以下をそのままCodexに渡す。

```text
あなたはこのリポジトリの実装担当です。目的は、現在の番号メニュー型 `mujina-assist` を、Mujina実機のセットアップ・診断・policy切替・zero position・SIM確認・実機起動までを扱うリッチなTUIアプリへ作り替えることです。

最重要方針:
1. `mujina_ros` を置き換えない。公式 `mujina_ros` の安全運用ラッパーとして作る。
2. ユーザーにコマンドを覚えさせない。通常入口は `./start.sh` でTUI起動。
3. ただし既存subcommandはテスト・自動化・緊急用に残す。
4. 実機起動はP0チェックが全てOKになるまで絶対にunlockしない。
5. external policyはmanifestとSIM verificationがない限り実機起動不可。
6. zero positionはwizard化し、post-zero verificationとzero profile保存を必須にする。
7. 公式 `mujina_ros` への改修が必要な場合は、直接混ぜ込まず `patches/mujina_ros/*.patch` として管理する。
8. `third_party/mujina_ros` を使う場合は公式clean mirrorとして扱い、LICENSEとcommit情報を保持する。
9. 実機にトルクを出す可能性がある操作は必ず強い確認を入れる。
10. 画面内に状態・ログ・次にやることを常に表示する。

まず現在のファイルを読んでください:
- `src/mujina_assist/app.py`
- `src/mujina_assist/models.py`
- `src/mujina_assist/services/*.py`
- `README.md`
- `pyproject.toml`
- `start.sh`
- `tests/*.py`

実装Phase 1:
- `textual` と `rich` を依存に追加する。
- `src/mujina_assist/tui/` を新設する。
- `DashboardScreen` を作る。
- 既存 `build_doctor_report()` とjob listを使って、状態カードを表示する。
- keybind: `d` doctor, `s` setup, `p` policy, `m` motors, `z` zero, `r` real, `l` logs, `?` help, `q` quit。
- `./start.sh` のdefaultはTUI起動にする。
- `./start.sh menu` または `mujina-assist menu --legacy` で旧メニューも使えるようにする。
- 既存テストを壊さない。
- 新しいTUI smoke testを追加する。

実装Phase 2:
- TUI画面を追加する: SetupFlowScreen, DeviceScreen, CANScreen, MotorScreen, ZeroWizardScreen, PolicyScreen, SimulationScreen, RealPreflightScreen, RealLaunchScreen, LogScreen。
- 各画面はまずmock/既存service呼び出しで動く状態にする。
- 長い処理は既存job systemを使う。
- jobのstdout/stderrはlog paneにtail表示できるようにする。

実装Phase 3:
- CAN診断を強化する。
- `ip -details -statistics link show can0` のparserを実装し、state/bitrate/errorsを表示する。
- slcand process検出を実装する。
- `can setup net`, `can setup serial`, `can reset`, `can dump` をTUI actionにする。

実装Phase 4:
- motor scanを強化する。
- 12軸のjoint名とmotor IDを表示する。
- scan結果をJSONとして保存する。
- timeout、温度、error code、last seenを表示する。

実装Phase 5:
- zero wizardを実装する。
- all / leg / single motorを選択できるようにする。
- pre-scan, stability check, confirmation, upstream zero script, post-scan, zero profile saveの順で進む。
- real launchはzero profileなしでは起動不可。

実装Phase 6:
- policy managerを強化する。
- ONNX input/output shape checkを実装する。
- manifest schemaを定義する。
- external policyはmanifestなしで実機不可。
- switch後はSIM verifiedをreset。
- hashとworkspace signatureをstateへ保存する。

実装Phase 7:
- real preflightとreal launchを段階化する。
- CAN setup → IMU node → IMU topic check → motor passive scan → mujina_main → robot_mode/motor_state check → joy node → joy topic check の順にする。
- 途中失敗時は可能な範囲でstop/rollbackし、manual recovery状態を表示する。

品質条件:
- `pytest -q` が通る。
- `ruff` が使えるなら通す。
- `__pycache__`, `.pytest_cache`, `*.pyc` をリポジトリに含めない。
- 実機がない環境でもTUI smoke testとservice parser testが通る。
- 実機操作系はmock可能にする。

UIの方向性:
- opencodeのように、起動したらTUIが立ち上がるアプリ的な体験にする。
- slash commandやcommand paletteはあってもよいが、基本操作は矢印・Enter・ショートカットキー。
- 状態が常に見える。
- NG理由と次の操作が常に出る。
- ユーザーが迷わない。
```

---

## 11. Codexへ渡す追加Prompt: `mujina_ros` patch管理

```text
このリポジトリでは公式 `mujina_ros` を直接破壊しない。公式を内包する場合は `third_party/mujina_ros` をclean mirrorとして保持する。

やること:
1. `third_party/mujina_ros` がある場合は、そのcommit hashとLICENSEをTUIに表示する。
2. `patches/mujina_ros` を作る。
3. patch適用サービスを作る。
4. setup時に `workspace/src/mujina_ros` へclean copy/cloneし、patchを適用する。
5. patch適用状態を `workspace_signature = upstream_commit + patch_set_hash + dirty` として計算する。
6. SIM verifiedはworkspace_signatureが変わったら無効にする。
7. Vanilla modeではpatchを適用しない。
8. Assisted modeではpatchを適用する。
9. TUIのDashboardに `vanilla` / `assisted patched` / `dirty` を表示する。

最初に作るpatch候補:
- CAN setup hardening
- IMU driver baud/format/port_fd fix
- mujina_main joy length check / mode command enum conversion / timestamp / init state fix

注意:
- patchが失敗したらsetupを止め、ログと復旧手順を表示する。
- patch適用済みworkspaceを公式そのものと誤認させない。
```

---

## 12. 完成目標

### MVP完成

- `./start.sh` でTUIが起動する。
- Dashboardで状態が一覧できる。
- SetupをTUIから開始できる。
- BuildをTUIから開始できる。
- policy一覧・切替・ONNX読み込みテストができる。
- SIM起動・SIM verified付与ができる。
- 実機前診断がTUIで見える。
- 旧番号メニューは残っている。
- テストが通る。

### 実機運用版完成

- Device/CAN/IMU/Joy/Motorの状態がTUIで常時見える。
- motor scanで12軸の状態が表で見える。
- zero wizardでzero設定とzero profile保存ができる。
- external policyはmanifestとSIM verifiedがないと実機起動不可。
- real preflightでNG理由が出る。
- real launchが段階起動になる。
- stop allが効く。
- ログとmanual recoveryが見える。

### 最高完成度

- `mujina_ros` のpatch queueを内包。
- vanilla/assisted mode切替可能。
- ROS topic rate / last message / quaternion norm / motor temp / CAN error counterがライブ更新。
- TUI内でlogsをtail表示。
- 実機なしでもmock profileでデモ可能。
- READMEとdocsが整っている。
- OSSとして配布可能。

---

## 13. READMEに入れるべき最短説明

````markdown
# Mujina Assist

Mujina Assist is a TUI application for setting up, diagnosing, and safely operating `mujina_ros`.

It is not a replacement for the official `mujina_ros`. It wraps the official workflow with guided setup, device checks, CAN diagnostics, policy management, zero-position wizard, simulation verification, and real-robot preflight.

## Start

```bash
./start.sh
```

The app opens an interactive terminal UI.

## Safety model

Real robot launch is locked until:

- workspace is built
- policy provenance is known
- external policy has manifest
- current policy is verified in simulation
- CAN is healthy
- IMU is publishing
- 12 motors respond
- zero profile is verified
- operator checklist is complete

## Upstream

This project can run official `mujina_ros` as-is or apply local patches in assisted mode. Patch state is always shown in the TUI.
````

---

## 14. 最重要の実装判断

1. **TUI-firstにする。**  
   旧メニューを育てるのではなく、Textualベースの画面を作る。

2. **サービス層をUI非依存にする。**  
   TUIでもsubcommandでも同じ診断ロジックを使う。

3. **公式 `mujina_ros` を直接壊さない。**  
   patch queue / assisted modeで管理する。

4. **real launchは最後の最後までlockする。**  
   便利さより事故防止。

5. **policyとzeroは記録する。**  
   実機で重要なのは「何を使って、いつ、誰が、どの状態で起動したか」。

6. **状態を常に見せる。**  
   実機ロボットのUXでは、メニュー項目より状態把握が大事。

---

## 15. 実装時に気をつける落とし穴

- `/dev/ttyUSB0` を勝手にIMU扱いしない。
- `can0` が存在するだけでOKにしない。
- `motor_test_read_only.py` という名前を完全安全と誤解しない。
- policy切替後にSIM verifiedを残さない。
- workspace commitやpatch hashが変わったのにSIM verifiedを残さない。
- zero設定後にpost verificationしないままreal launchをunlockしない。
- GUI terminalをkillしただけで子プロセスが止まったと思い込まない。
- ROS nodeが残っているのに次のlaunchへ進まない。
- 実機起動時にIMU/main/joyを同時起動して、どれが失敗したか分からない状態にしない。

---

## 16. 最終UIの一言コンセプト

**Mujina Assistは、mujina_rosを安全に使うための「実機運用コックピット」。**

コマンドを覚えるツールではない。  
状態を見て、次に進めるか判断し、危ないときは止めてくれるターミナルアプリにする。
