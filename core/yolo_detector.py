import os
import cv2
import numpy as np
from ultralytics import YOLO

class YoloDetector:
    def __init__(self, model_path):
        # 确保权重文件存在
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"YOLO 权重文件未找到: {model_path}")
        
        self.model = YOLO(model_path)

    def detect(self, image_path):
        """
        检测图像中的目标，返回带旋转框的信息。
        返回格式:
        [
            {
                "class_id": int,
                "class_name": str,
                "confidence": float,
                "x_center": float,
                "y_center": float,
                "width": float,
                "height": float,
                "angle": float  # 弧度
            }, ...
        ]
        """
        results = self.model(image_path, conf=0.15, iou=0.4, imgsz=1024)
        detections = []
        
        for result in results:
            if result.obb:
                # OBB 模型 (xywhr)
                xywhr = result.obb.xywhr.cpu().numpy()
                cls_ids = result.obb.cls.cpu().numpy()
                confs = result.obb.conf.cpu().numpy()
                
                for i in range(len(cls_ids)):
                    class_id = int(cls_ids[i])
                    x, y, w, h, r = xywhr[i]
                    detections.append({
                        "class_id": class_id,
                        "class_name": self.model.names[class_id],
                        "confidence": float(confs[i]),
                        "x_center": float(x),
                        "y_center": float(y),
                        "width": float(w),
                        "height": float(h),
                        "angle": float(r)
                    })
            elif result.boxes:
                # 标准 HBB 模型 (xywh)
                xywh = result.boxes.xywh.cpu().numpy()
                cls_ids = result.boxes.cls.cpu().numpy()
                confs = result.boxes.conf.cpu().numpy()
                
                for i in range(len(cls_ids)):
                    class_id = int(cls_ids[i])
                    x, y, w, h = xywh[i]
                    detections.append({
                        "class_id": class_id,
                        "class_name": self.model.names[class_id],
                        "confidence": float(confs[i]),
                        "x_center": float(x),
                        "y_center": float(y),
                        "width": float(w),
                        "height": float(h),
                        "angle": 0.0  # 默认无旋转
                    })
                    
        return detections

    def draw_detections(self, image, detections):
        """
        在图像上绘制检测到的目标（仅作可视化调试用，GUI 会自己画）
        """
        img = image.copy()
        for det in detections:
            x, y, w, h, r = det['x_center'], det['y_center'], det['width'], det['height'], det['angle']
            # 将中心坐标、宽高、角度转换为旋转矩形的四个顶点
            rect = ((x, y), (w, h), np.degrees(r))
            box = cv2.boxPoints(rect)
            box = np.int0(box)
            cv2.drawContours(img, [box], 0, (0, 255, 0), 2)
            cv2.putText(img, f"{det['class_name']} {det['confidence']:.2f}", 
                        (int(x), int(y)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
        return img
