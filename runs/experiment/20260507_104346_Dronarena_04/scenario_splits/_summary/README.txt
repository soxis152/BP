Souhrn scenario evaluace

Tato slozka obsahuje post-processed vystupy offline pipeline pro porovnani
scenaru senzoru proti OptiTracku.

Struktura:
- evaluation_summary.json
  Strojove citelny souhrn celeho behu.
- position/
  Evaluace scenaru v hlavni 3D sekci:
  radar1, radar2, radar1_ble1, radar2_ble2, 2x_radar, 2x_ble, radar1_2x_ble, radar2_2x_ble, fusion
- position/tables/
  Per-target serazene tabulky s 3D metrikami.
- position/boxplots/
  Per-target boxploty rozdeleni 3D chyby.
- ble_only/
  Evaluace single-BLE scenaru: ble1, ble2
- ble_only/tables/
  Per-target serazene tabulky BLE-only metrik.
- ble_only/boxplots/
  Per-target boxploty ray distance a angle error.
- radar_ble_single_anchor/
  Offline evaluace scenaru radar1_ble1, radar2_ble2, 2x_radar_ble1 a 2x_radar_ble2
- radar_ble_single_anchor/tables/
  Per-target serazene tabulky pro radar cluster vybrany podle BLE paprsku.
- radar_ble_single_anchor/boxplots/
  Per-target boxploty 3D chyby pro single-anchor radar+BLE evaluaci.

Per-scenario slozky:
- <scenario>/position_eval/
  Per-target stats JSON + 2D mapa + timeline 3D chyby + XYZ timeline.
- <scenario>/ble_only_eval/
  Per-target stats JSON + ray-distance timeline + angle-error timeline.
- <scenario>/single_anchor_eval/
  Per-target stats JSON + 2D mapa + timeline 3D chyby + XYZ timeline + cluster-ray timeline.

Rozdeleni metrik:
- position metriky porovnavaji odhadnutou 3D pozici proti OptiTracku
- nektere scenare mohou v aktualni fusion logice skoncit jako no_data,
  pokud nevytvori tagovanou 3D pozici pro dany cil
- radar_ble_single_anchor pouziva offline heuristiku:
  pro kazdy BLE paprsek vezme radar cluster nejblizsi paprsku
- BLE-only metriky neporovnavaji plnou 3D pozici, ale:
  - ray distance: kolma vzdalenost GT bodu od BLE paprsku
  - angle error: uhlova chyba mezi BLE paprskem a smerem na GT

Doporucene poradi otevreni:
1. _summary/position/tables/summary_table_Phantom4.jpg
2. _summary/position/tables/summary_table_Vysavac3.jpg
3. _summary/radar_ble_single_anchor/tables/
4. _summary/position/boxplots/
5. _summary/ble_only/tables/
6. detailni slozky jednotlivych scenaru
