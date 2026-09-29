# Samples

## Videos

Sample videos are not committed to the repository. Run

```
python scripts/download_samples.py
```

to download two short clips into `samples/videos/`:

| File | Content | Source | Licence |
| --- | --- | --- | --- |
| `people-detection.mp4` | People walking through an indoor corridor, 768x432, 12 fps, 50 s | [intel-iot-devkit/sample-videos](https://github.com/intel-iot-devkit/sample-videos) | CC-BY-4.0 |
| `person-bicycle-car-detection.mp4` | A street with a pedestrian, a cyclist and a car, 768x432, 12 fps, 54 s | [intel-iot-devkit/sample-videos](https://github.com/intel-iot-devkit/sample-videos) | CC-BY-4.0 |

Attribution: Intel IoT DevKit sample videos, Creative Commons Attribution 4.0.

## Scenes

`scenes/corridor_route_choice.json` is a scene configuration for
`people-detection.mp4`: an entrance gate in the middle of the corridor, exit
gates on the left and right, a centre-floor zone and two routes
(Entrance -> Exit Left = Route A, Entrance -> Exit Right = Route B).

Load it from the Scene Builder with **Import JSON** or post it to
`/api/cameras/{camera_id}/scenes`.

## Experiments

`experiments/route_choice.json` is the matching experiment body for
`POST /api/experiments` (adjust `project_id` and `camera_id`).
