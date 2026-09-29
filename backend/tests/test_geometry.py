from pathscope.domain.scene import Calibration, CalibrationPoint, KnownDistance, Point
from pathscope.spatial.calibration import GroundMapper
from pathscope.spatial.geometry import (
    box_iou_matrix,
    forward_normal,
    path_length,
    point_in_polygon,
    polygon_area,
    segment_crossing,
    side_of_line,
)


def test_segment_crossing_direction_matches_forward_normal():
    a, b = (0.5, 0.0), (0.5, 1.0)  # vertical line, A at top
    n = forward_normal(a, b)
    # A point on the positive side is in the direction of the normal
    p_pos = (0.5 + n[0] * 0.1, 0.5 + n[1] * 0.1)
    assert side_of_line(a, b, p_pos) > 0
    p_neg = (0.5 - n[0] * 0.1, 0.5 - n[1] * 0.1)
    crossed, direction, u = segment_crossing(a, b, p_neg, p_pos)
    assert crossed and direction == "forward" and 0.4 < u < 0.6
    crossed, direction, _ = segment_crossing(a, b, p_pos, p_neg)
    assert crossed and direction == "reverse"


def test_segment_crossing_outside_segment_is_ignored():
    a, b = (0.5, 0.4), (0.5, 0.6)
    assert segment_crossing(a, b, (0.4, 0.9), (0.6, 0.9))[0] is False
    assert segment_crossing(a, b, (0.4, 0.5), (0.4, 0.55))[0] is False  # no side change


def test_point_in_polygon_and_area():
    square = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]
    assert point_in_polygon((0.5, 0.5), square)
    assert not point_in_polygon((0.9, 0.5), square)
    assert abs(polygon_area(square) - 0.36) < 1e-9


def test_path_length():
    assert abs(path_length([(0, 0), (3, 4), (3, 4)]) - 5.0) < 1e-9


def test_iou_matrix():
    m = box_iou_matrix([[0, 0, 10, 10]], [[0, 0, 10, 10], [5, 5, 15, 15], [20, 20, 30, 30]])
    assert abs(m[0, 0] - 1.0) < 1e-9
    assert abs(m[0, 1] - 25 / 175) < 1e-9
    assert m[0, 2] == 0.0


def test_ground_mapper_modes():
    none = GroundMapper.from_calibration(None, 1000, 500)
    assert none.mode == "none" and none.to_ground(0.5, 0.5) == (0.5, 0.5)

    scale = GroundMapper.from_calibration(
        Calibration(known_distance=KnownDistance(a=Point(x=0.0, y=0.5), b=Point(x=0.5, y=0.5), distance=10.0)), 1000, 500
    )
    assert scale.mode == "scale"
    assert abs(scale.distance((0.0, 0.5), (0.5, 0.5)) - 10.0) < 1e-6

    pts = [
        CalibrationPoint(image=Point(x=0.1, y=0.1), ground_x=0, ground_y=0),
        CalibrationPoint(image=Point(x=0.9, y=0.1), ground_x=8, ground_y=0),
        CalibrationPoint(image=Point(x=0.9, y=0.9), ground_x=8, ground_y=4),
        CalibrationPoint(image=Point(x=0.1, y=0.9), ground_x=0, ground_y=4),
    ]
    homo = GroundMapper.from_calibration(Calibration(points=pts), 1000, 500)
    assert homo.mode == "homography"
    gx, gy = homo.to_ground(0.5, 0.5)
    assert abs(gx - 4.0) < 1e-6 and abs(gy - 2.0) < 1e-6
    assert abs(homo.distance((0.1, 0.1), (0.9, 0.1)) - 8.0) < 1e-6
