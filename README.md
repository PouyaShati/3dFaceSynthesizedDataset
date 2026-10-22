# Monthly dual momentum for US, Europe, and Canada ETFs

Educational research script, not a recommendation to buy or sell any fund. You can lose the money you put in. The backtest is not a forecast. Nothing here sends an order to a broker.

The rule is monthly dual momentum on three equity ETFs:

- `QQQ` — US Nasdaq-100
- `VGK` — developed Europe
- `EWC` — Canada
- `SGOV` — cash when every equity score is zero or negative

Once a month, on the last session, each equity ETF is scored on its total return over the previous **126 trading days** (about six months). The account holds **100%** of the ETF with the highest score if that score is above zero. Otherwise it holds cash. The order is filled at the **next session's close**. That fill session is not an input to the score, and its move is still earned by the previous holding. There is no leverage and no intraday trading.

A **3% round trip** is large next to a typical day in these ETFs. The script therefore runs the same positions at three costs, **3%**, **0.5%**, and **0.05%**, and prints the 3% result first. Fee drag is the gap in compound annual growth versus the same signals at a 0% fee. A 63-day lookback is printed only to check that the fee ranking does not flip. The live signal stays on 126 days.

Switching from one traded fund to another, including `SGOV` into an equity ETF, costs the full round-trip fee (you sell one fund and buy the other). The UCITS preset has no cash fund: uninvested cash earns zero and costs half a round trip to enter or leave.

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 scripts/run_backtest.py
python3 scripts/today_signal.py
python3 -m unittest discover -s tests -v
```

`run_backtest.py` writes `output/fee_comparison.png`. Prices are cached under `data/cache/`. Pass `--refresh` after you want a new download. Pass `--preset ucits` only if your broker blocks US ETFs.

The UCITS preset is `CNDX.L` (iShares Nasdaq 100 UCITS USD Acc) and `VEUR.L` (Vanguard FTSE Developed Europe UCITS). Confirm those listings yourself. Canada is not included. Each score is that listing's own total return; the model does not hedge currency.

`today_signal.py` prints the month-end target and the three scores. If the latest bar is not the month-end, the latest scores are informational and are not an order. Place any trade yourself.

Read the 3% block before changing lookbacks, adding a fund, or placing a trade. If that block is flat or negative, the next step is a cheaper broker, not a new indicator. Prefer a regulated broker with near-zero ETF commission, and convert currency once when you fund the account.

## Other files in this repository

The `synthesized`, `synthesized2`, and `synthesized3` folders are a separate face-image set and are not used by this model:

We used the Unity Multipurpose Avatar asset for the Unity 3D game engine to generate and render faces. First, we generated 50 random 3d models of human faces. Then we placed each of the models to face a camera 1 meter away, and added three different light sources to the environment: A backlight of 0.4 Candelas, a filler light of 0.33 Candelas, and a point light source 1 meter away from the face in the $x=y$ direction, randing from 0 to 3 Candelas. Using this environment, we generated three sub-datasets:

- synthesized folder: For each face, we rotated it around the z axis from -45 degrees to +45 degrees, and captured an image for every 9 degrees of rotation (0 degrees means that the model is facing the camera). We generated a total of 550 human face images with different rotations.

- synthesized2 folder: For each face, we changed the point light intensity from 0 to 3 Candelas, capturing an image after every 0.3 Candela step. Consequently, we generated 550 images with different levels of lighting.

- synthesized3 folder: For each face, we randomly modified 27 different features of the face, changing its expression. Given there are no quantitative measures of facial expression, we bounded the modification levels so the faces be realistic and also span throught the whole range of reasonable facial expressions. Applying different levels of expression intensity, we generated 11 images from each face, resulting in 550 images.
