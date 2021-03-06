import cv2
import platform
from PIL import Image
import face_recognition
from edgetpu.detection.engine import DetectionEngine
from queue import Queue
from multiprocessing import Process
import multiprocessing
import time
from time import sleep
import math
from sklearn import neighbors
import os
import os.path
import pickle
from http import server
import socketserver
import logging
import numpy as np
from datetime import datetime, timedelta

HTML_PAGE="""\
<html>
<head>
<title>Face recognition</title>
</head>
<body>
<center><h1>Cam</h1></center>
<center><img src="stream.mjpg" width="1280" height="720" /></center>
</body>
</html>
"""

def camThread(frameBuffer, results, MJPEGQueue, persBuffer, stop_prog, file2log):
    capture_width=1920
    capture_height=1080
    frame_rate=21
    flip_method=2
    display_width=1280
    display_height=720
    record_width=1280
    record_height=720
    # gstreamer_pipeline = ('nvarguscamerasrc !  video/x-raw(memory:NVMM), width={capturewidth}, height={captureheight}, framerate={framerate}/1, format=NV12 '
    #     '! tee name=streams streams. ! queue ! nvvidconv flip-method={flipmethod} ! video/x-raw, width={displaywidth}, height={displayheight}, frame_rate={framerate}/1, '
    #     'format=BGRx ! videoconvert ! video/x-raw, format=BGR ! appsink '
    #     'streams. ! nvvidconv ! video/x-raw, width={recordwidth}, height={recordheight}, frame_rate={framerate}/1 ! '
    #     'omxh264enc preset-level=2 profile=2 control-rate=1 '
    #     '! video/x-h264 ! avimux ! queue ! filesink location={fname}').format(capturewidth=capture_width, captureheight=capture_height, framerate=frame_rate, displaywidth=display_width,
    #     displayheight=display_height, recordwidth=record_width, recordheight=record_height, fname=file2log, flipmethod=flip_method)
    #gstreamer_pipeline = ('nvarguscamerasrc !  video/x-raw(memory:NVMM), width={capturewidth}, height={captureheight}, framerate={framerate}/1, format=NV12 '
    #    '! tee name=streams streams. ! queue ! nvvidconv flip-method={flipmethod} ! video/x-raw, width={displaywidth}, height={displayheight}, frame_rate={framerate}/1, '
    #    'format=BGRx ! videoconvert ! video/x-raw, format=BGR ! appsink ').format(capturewidth=capture_width, captureheight=capture_height, framerate=frame_rate, displaywidth=display_width,
    #    displayheight=display_height, flipmethod=flip_method)
    os.system('v4l2-ctl --set-ctrl=zoom_absolute=150')
    gstreamer_pipeline = ('v4l2src device=/dev/video0 do-timestamp=true !  video/x-raw, width=1280, height=720, framerate=30/1 ! tee name=streams streams. ! nvvidconv ! videoflip method=4 ! video/x-raw ! videoconvert ! video/x-raw, format=BGR ! appsink')
    cam = cv2.VideoCapture(gstreamer_pipeline, cv2.CAP_GSTREAMER)
    # cam = cv2.VideoCapture(0)
    # cam.set(cv2.CAP_PROP_FPS, 15)
    # cam.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    # cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    main_window_name = 'Video'
    cv2.namedWindow(main_window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(main_window_name, 1280,720)
    cv2.moveWindow(main_window_name, 80,20)
    aux_window_name = 'Persons'
    cv2.namedWindow(aux_window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(aux_window_name, 330,1080)
    cv2.moveWindow(aux_window_name, 1500,20)
    t0 = time.monotonic()
    last_result=None
    frames_cnt = 0
    persons=None
    blank_persons = 255*np.ones(shape=[330,1080,3], dtype=np.uint8)
    while True:
        ret, frame = cam.read()
        if not ret:
            continue
        if frameBuffer.empty():
            frameBuffer.put(frame.copy())
        res = None
        if not results.empty():
            res = results.get(False)
            imdraw = overlay_on_image(frame, res)
            last_result = res
        else:
            imdraw = overlay_on_image(frame,last_result)
        if not persBuffer.empty():
            persons = persBuffer.get(False)
        blank_persons = 255*np.ones(shape=[1080,330,3], dtype=np.uint8)
        blank_persons = overlay_faces(blank_persons, persons)
        cv2.imshow(aux_window_name, blank_persons)
        cv2.imshow(main_window_name, imdraw)
        frames_cnt += 1
        if frames_cnt >= 15:
            t1 = time.monotonic()
            print('FPS={d:.1f}'.format(d = frames_cnt/(t1-t0)))
            frames_cnt = 0
            t0 = t1
        if not MJPEGQueue.full():
            MJPEGQueue.put(imdraw)
        if (cv2.waitKey(1) & 0xFF == ord('q')):
            stop_prog.set()
            break
    cam.release()

def overlay_faces(frame, persons):
    img = frame.copy()
    if isinstance(persons, type(None)):
        return img
    x = 0
    y = 0
    for person in persons:
        img[y:y+216, x:x+330] = person["face_image"]
        if person["seen_count"] == 1:
            visit_label = "First visit"
        else:
            visit_label = "{} visits".format(person["seen_count"])
        #cv2.putText(img, visit_label, (x, y+184), cv2.FONT_HERSHEY_DUPLEX, 0.8, (255,0,0), 2)
        #cv2.putText(img, person["name"], (x, y+200), cv2.FONT_HERSHEY_DUPLEX, 0.8, (255,0,0), 2)
        y += 216
        if y >= 1080:
            break
    return img

def overlay_on_image(frame, result):
    if isinstance(result, type(None)):
        return frame.copy()
    img = frame.copy()
    boxes = result["boxes"]
    encod = result["names"]
    for box, name in zip(boxes,encod):
        y0, x1, y1, x0 = box
        cv2.rectangle(img, (x0,y0), (x1,y1), (255,0,0), 3)
        #cv2.putText(img, '{d}'.format(d=name), (x0+6,y1-6), cv2.FONT_HERSHEY_DUPLEX, 0.8, (255,0,0), 2)
    return img

def greeting(namesBuffer, stop_prog):
    greet_persons={}
    for class_dir in os.listdir("/home/robo/visi/Jetson-Nano-FaceRecognition/Faces/"):
        greet_path=os.path.join("/home/robo/visi/Jetson-Nano-FaceRecognition/Faces/", class_dir, "Greet.ogg")
        strSound='gst-launch-1.0 filesrc location="{}" ! oggdemux ! opusdec ! audioconvert ! audioresample ! pulsesink'.format(greet_path)
        greet_persons[class_dir]={
            "greet_path": greet_path,
            "greet_command": strSound,
            "name": class_dir,
            "first_seen": 0
        }
    while True:
        if stop_prog.is_set():
            break
        if namesBuffer.empty():
            continue
        names = namesBuffer.get()
        if isinstance(names, type(None)):
            continue
        for name in names:
            if greet_persons.get(name) != None:
                if greet_persons[name]["first_seen"] == 0:
                    greet_persons[name]["first_seen"] = 1
                    print('Greeting {}!'.format(name))
                    os.system(greet_persons[name]["greet_command"])
                    sleep(2)
                    break
        names = []        

def recognition(frameBuffer, objsBuffer, persBuffer, namesBuffer, stop_prog):
    engine = DetectionEngine('mobilenet_ssd_v2_face_quant_postprocess_edgetpu.tflite')
    with open("trained_knn_model.clf", 'rb') as f:
        knn_clf = pickle.load(f)
    known_persons={}
    for class_dir in os.listdir("/home/robo/visi/Jetson-Nano-FaceRecognition/Faces/"):
        face_image = cv2.imread(os.path.join("/home/robo/visi/Jetson-Nano-FaceRecognition/Faces/", class_dir, "face_ID.jpg"))
        #face_image = cv2.resize(face_image, (288,216))
        known_persons[class_dir]={
            "first_seen": datetime(1,1,1),
            "name": class_dir,
            "first_seen_this_interaction": datetime(1,1,1),
            "last_seen": datetime(1,1,1),
            "seen_count": 0,
            "seen_frames": 0,
            "face_image": face_image
        }
    while True:
        if stop_prog.is_set():
            break
        if frameBuffer.empty():
            continue
        t0 = time.monotonic()
        bgr_img = frameBuffer.get()
        rgb_img = bgr_img[:, :, ::-1].copy()
        arr_img = Image.fromarray(rgb_img)
        t1 = time.monotonic()
        objs = engine.detect_with_image(arr_img, threshold = 0.1, keep_aspect_ratio = True, relative_coord = False, top_k = 100)
        t2 = time.monotonic()
        coral_boxes = []
        for obj in objs:
            x0, y0, x1, y1 = obj.bounding_box.flatten().tolist()
            w = x1-x0
            h = y1-y0
            x0 = int(x0+w/10)
            y0 = int(y0+h/4)
            x1 = int(x1-w/10)
            y1 = int(y1)
            coral_boxes.append((y0, x1, y1, x0))
        t3 = time.monotonic()
        kk = 1
        if coral_boxes:
            enc = face_recognition.face_encodings(rgb_img, coral_boxes)
            closest_distances = knn_clf.kneighbors(enc, n_neighbors=1)
            are_matches = [closest_distances[0][i][0] <= 0.45 for i in range(len(coral_boxes))]
            predR = []
            locR = []
            for pred, loc, rec in zip(knn_clf.predict(enc), coral_boxes, are_matches):
                if rec:
                    person_found = known_persons.get(pred)
                    if person_found != None:
                        if known_persons[pred]["first_seen"] != datetime(1,1,1):
                            known_persons[pred]["last_seen"] = datetime.now()
                            known_persons[pred]["seen_frames"] += 1
                            if datetime.now() - known_persons[pred]["first_seen_this_interaction"] > timedelta(minutes=5):
                                known_persons[pred]["first_seen_this_interaction"] = datetime.now()
                                known_persons[pred]["seen_count"] += 1
                                known_persons[pred]["seen_frames"] = 0
                        else:
                            known_persons[pred]["first_seen"] = datetime.now()
                            known_persons[pred]["last_seen"] = datetime.now()
                            known_persons[pred]["seen_count"] += 1
                            known_persons[pred]["first_seen_this_interaction"] = datetime.now()
                    predR.append(pred)
                else:
                    predR.append("unknown_{n}".format(n=kk))
                    kk += 1
                locR.append(loc)
            if objsBuffer.empty():
                objsBuffer.put({"boxes": locR, "names": predR})
        else:
            if objsBuffer.empty():
                objsBuffer.put(None)
        dtnow = datetime.now()
        visi_faces = []
        for pers in known_persons:
            if datetime.now()-known_persons[pers]["last_seen"]>timedelta(seconds=4):
                known_persons[pers]["seen_frames"] = 0
            #if dtnow-known_persons[pers]["last_seen"] < timedelta(seconds=10) and known_persons[pers]["seen_frames"] > 30:
            if known_persons[pers]["seen_frames"] > 10:
                visi_faces.append(known_persons[pers])
        if persBuffer.empty():
            if len(visi_faces) > 0:
                if namesBuffer.empty():
                    pp = []
                    for f in visi_faces:
                        pp.append(f["name"])
                    namesBuffer.put(pp)
                persBuffer.put(visi_faces)
            else:
                if namesBuffer.empty():
                    namesBuffer.put(None)
                persBuffer.put(None)
        t4 = time.monotonic()
        #print('Prep time = {dt1:.1f}ms, Infer time = {dt2:.1f}ms, Face enc time = {dt3:.1f}ms, Overall time = {dt4:.1f}ms'.format(
        #    dt1=(t1-t0)*1000, dt2=(t2-t1)*1000, dt3=(t4-t3)*1000, dt4 = (t4-t0)*1000))

class StreamingHandler(server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(301)
            self.send_header('Location', '/index.html')
            self.end_headers()
        elif self.path == '/index.html':
            stri = HTML_PAGE
            content = stri.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Conent-Length', len(content))
            self.end_headers()
            self.wfile.write(content)
        # elif self.path == '/data.html':
        #     stri = coral_engine.result_str
        #     content = stri.encode('utf-8')
        #     self.send_response(200)
        #     self.send_header('Content-Type', 'text/html')
        #     self.send_header('Conent-Length', len(content))
        #     self.end_headers()
        #     self.wfile.write(content)
        elif self.path == '/stream.mjpg':
            self.send_response(200)
            self.send_header('Age', 0)
            self.send_header('Cache-Control', 'no-cache, private')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()
            try:
                while True:
                    if not self.server.MJPEGQueue.empty():
                        frame = self.server.MJPEGQueue.get()
                        ret, buf = cv2.imencode('.jpg', frame)
                        frame = np.array(buf).tostring()
                        self.wfile.write(b'-FRAME\r\n')
                        self.send_header('Content-Type', 'image/jpeg')
                        self.send_header('Content-Length', len(frame))
                        self.end_headers()
                        self.wfile.write(frame)
                        self.wfile.write(b'\r\r')
            except Exception as e:
                logging.warning('Removed streaming clients %s: %s', self.client_address, str(e))
        else:
            self.send_error(404)
            self.end_headers()

class StreamingServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

def server_start(frameQueue, exit_key):
    try:
        address = ('', 8000)
        server = StreamingServer(address, StreamingHandler)
        server.MJPEGQueue = frameQueue
        print('Started server')
        server.serve_forever()
    finally:
        # Release handle to the webcam
        exit_key.set()

if __name__ == '__main__':
    multiprocessing.set_start_method('forkserver')
    prog_stop = multiprocessing.Event()
    prog_stop.clear()
    prog_stop1 = multiprocessing.Event()
    prog_stop1.clear()
    recImage = multiprocessing.Queue(2)
    resultRecogn = multiprocessing.Queue(2)
    persBuffer = multiprocessing.Queue(2)
    MJPEGQueue = multiprocessing.Queue(10)
    NamesQueue = multiprocessing.Queue(2)
    camProc = Process(target=camThread, args=(recImage, resultRecogn, MJPEGQueue, persBuffer,  prog_stop, 'test.avi'), daemon=True)
    camProc.start()
    frecogn = Process(target=recognition, args=(recImage, resultRecogn, persBuffer, NamesQueue, prog_stop), daemon=True)
    frecogn.start()
    greet = Process(target=greeting, args=(NamesQueue, prog_stop), daemon=True)
    greet.start()
    serverProc = Process(target=server_start, args=(MJPEGQueue, prog_stop1), daemon=True)
    serverProc.start()

    while True:
        if prog_stop.is_set():
            camProc.terminate()
            frecogn.terminate()
            greet.terminate()
            serverProc.terminate()
            break
        sleep(1)
    cv2.destroyAllWindows()
