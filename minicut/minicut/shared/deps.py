"""Common imports (stdlib, numpy, OpenCV, PIL, Qt) shared by every module."""
import sys
import os, re, json, uuid, time, math, copy, wave, subprocess, tempfile, threading, datetime
from collections import OrderedDict
import numpy as np
import cv2
from PIL import Image, ImageSequence
import imageio_ffmpeg
from PySide6.QtCore import (Qt, QObject, Signal, QTimer, QElapsedTimer, QPoint, QPointF, QRectF, QRect, QSize, QLineF,
    QUrl, QMimeData, QThread, QThreadPool, QRunnable, QPropertyAnimation, QVariantAnimation, QEasingCurve,
    QParallelAnimationGroup, QEvent, QBuffer, QByteArray, QIODevice)
from PySide6.QtGui import (QColor, QPainter, QPen, QBrush, QFont, QFontMetrics, QImage, QPixmap, QIcon,
    QPainterPath, QPainterPathStroker, QPolygonF, QKeySequence, QAction, QDrag, QCursor, QLinearGradient)
from PySide6.QtWidgets import *
try:
    from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices
    HAS_AUDIO = True
except Exception:
    HAS_AUDIO = False
