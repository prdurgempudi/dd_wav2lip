import argparse
import math
import os
import platform
import subprocess

import cv2
import numpy as np
import torch, face_detection
from tqdm import tqdm

import audio
# from face_detect import face_rect
from models import Wav2Lip

from batch_face import RetinaFace
from time import time

import json

args = {
    'checkpoint_path': "D:/new/Wav2Lip/checkpoints/wav2lip_gan.pth",
    'face': "D:/new/sample_data/uploaded.mp4",
    'audio': "D:/new/translated_audio/translated.wav",
    'outfile': "D:/new/converted_videos/output.mp4",
    'static': False,
    'fps': 25.,
    'pads': [0, 10, 0, 0],
    'face_det_batch_size': 16,
    'wav2lip_batch_size': 128,
    'resize_factor': 1,
    'crop': [0, -1, 0, -1],
    'box': [-1, -1, -1, -1],
    'rotate': False,
    'nosmooth': False,
    'img_size': 96
}

# Save the dictionary as a JSON file
with open('args[json', 'w') as json_file:
    json.dump(args, json_file)


# def load_model(path):
#     model = Wav2Lip()
#     print("Load checkpoint from: {}".format(path))
#     checkpoint = _load(path)
#     s = checkpoint["state_dict"]
#     new_s = {}
#     for k, v in s.items():
#         new_s[k.replace('module.', '')] = v
#     model.load_state_dict(new_s)

#     model = model.to(device)
#     return model.eval()

# model = detector = detector_model = None

# def do_load(checkpoint_path):
#     global model, detector, detector_model

#     model = load_model(checkpoint_path)

#     # SFDDetector.load_model(device)
#     detector = RetinaFace(gpu_id=0, model_path="checkpoints/mobilenet.pth", network="mobilenet")
#     # detector = RetinaFace(gpu_id=0, model_path="checkpoints/resnet50.pth", network="resnet50")

#     detector_model = detector.model

#     print("Models loaded")

# face_batch_size = 64 * 8

# def face_rect(images):
#     num_batches = math.ceil(len(images) / face_batch_size)
#     prev_ret = None
#     for i in range(num_batches):
#         batch = images[i * face_batch_size: (i + 1) * face_batch_size]
#         all_faces = detector(batch)  # return faces list of all images
#         for faces in all_faces:
#             if faces:
#                 box, landmarks, score = faces[0]
#                 prev_ret = tuple(map(int, box))
#             yield prev_ret

def get_smoothened_boxes(boxes, T):
    for i in range(len(boxes)):
        if i + T > len(boxes):
            window = boxes[len(boxes) - T:]
        else:
            window = boxes[i : i + T]
        boxes[i] = np.mean(window, axis=0)
    return boxes

def face_detect(images):
    detector = face_detection.FaceAlignment(face_detection.LandmarksType._2D, 
                                                flip_input=False, device=device)

    batch_size = args['face_det_batch_size']
    
    while 1:
        predictions = []
        try:
            for i in tqdm(range(0, len(images), batch_size)):
                predictions.extend(detector.get_detections_for_batch(np.array(images[i:i + batch_size])))
        except RuntimeError:
            if batch_size == 1: 
                raise RuntimeError('Image too big to run face detection on GPU. Please use the --resize_factor argument')
            batch_size //= 2
            print('Recovering from OOM error; New batch size: {}'.format(batch_size))
            continue
        break

    results = []
    pady1, pady2, padx1, padx2 = args['pads']
    for rect, image in zip(predictions, images):
        if rect is None:
            # Add the original frame without face to results
            results.append([image, []])
            # cv2.imwrite('temp/faulty_frame.jpg', image) # check this frame where the face was not detected.
            # raise ValueError('Face not detected! Ensure the video contains a face in all the frames.')

        y1 = max(0, rect[1] - pady1)
        y2 = min(image.shape[0], rect[3] + pady2)
        x1 = max(0, rect[0] - padx1)
        x2 = min(image.shape[1], rect[2] + padx2)
        
        results.append([x1, y1, x2, y2])

    boxes = np.array(results)
    if not args['nosmooth']: boxes = get_smoothened_boxes(boxes, T=5)
    results = [[image[y1: y2, x1:x2], (y1, y2, x1, x2)] for image, (x1, y1, x2, y2) in zip(images, boxes)]
    
    del detector
    return results 

def datagen(frames, mels):
    img_batch, mel_batch, frame_batch, coords_batch = [], [], [], []

    if args['box'][0] == -1:
        if not args['static']:
            face_det_results = face_detect(frames) # BGR2RGB for CNN face detection
        else:
            face_det_results = face_detect([frames[0]])
    else:
        print('Using the specified bounding box instead of face detection...')
        y1, y2, x1, x2 = args['box']
        face_det_results = [[f[y1: y2, x1:x2], (y1, y2, x1, x2)] for f in frames]

    for i, m in enumerate(mels):
        idx = 0 if args['static'] else i%len(frames)
        frame_to_save = frames[idx].copy()
        face, coords = face_det_results[idx].copy()

        if len(coords) == 0: # Check if there are no face coordinates
            # Add a random matrix of shape (96x96x3) to img_batch and an empty list to coords_batch
            face = np.random.rand(args['img_size'], args['img_size'], 3) * 255
            coords_batch.append([])
        else:
            face = cv2.resize(face, (args['img_size'], args['img_size']))

        img_batch.append(face)
        mel_batch.append(m)
        frame_batch.append(frame_to_save)
        # coords_batch.append(coords)

        if len(img_batch) >= args['wav2lip_batch_size']:
            img_batch, mel_batch = np.asarray(img_batch), np.asarray(mel_batch)

            img_masked = img_batch.copy()
            img_masked[:, args['img_size']//2:] = 0

            img_batch = np.concatenate((img_masked, img_batch), axis=3) / 255.
            mel_batch = np.reshape(mel_batch, [len(mel_batch), mel_batch.shape[1], mel_batch.shape[2], 1])

            yield img_batch, mel_batch, frame_batch, coords_batch
            img_batch, mel_batch, frame_batch, coords_batch = [], [], [], []

    if len(img_batch) > 0:
        img_batch, mel_batch = np.asarray(img_batch), np.asarray(mel_batch)

        img_masked = img_batch.copy()
        img_masked[:, args['img_size']//2:] = 0

        img_batch = np.concatenate((img_masked, img_batch), axis=3) / 255.
        mel_batch = np.reshape(mel_batch, [len(mel_batch), mel_batch.shape[1], mel_batch.shape[2], 1])

        yield img_batch, mel_batch, frame_batch, coords_batch

mel_step_size = 16
device = 'cuda' if torch.cuda.is_available() else 'cpu'
print('Using {} for inference.'.format(device))

def _load(checkpoint_path):
    if device == 'cuda':
        checkpoint = torch.load(checkpoint_path)
    else:
        checkpoint = torch.load(checkpoint_path,
                                map_location=lambda storage, loc: storage)
    return checkpoint

def load_model(path):
	model = Wav2Lip()
	print("Load checkpoint from: {}".format(path))
	checkpoint = _load(path)
	s = checkpoint["state_dict"]
	new_s = {}
	for k, v in s.items():
		new_s[k.replace('module.', '')] = v
	model.load_state_dict(new_s)

	model = model.to(device)
	return model.eval()

def convert(audio_file, video_file, checkpoint_path, final_output_directory):
    args['face'] = video_file
    args['audio'] = audio_file
    args['checkpoint_path'] = checkpoint_path
    print("generating video")

    if os.path.isfile(args['face']) and args['face'].split('.')[1] in ['jpg', 'png', 'jpeg']:
        args['static'] = True

    if not os.path.isfile(args['face']):
        raise ValueError('--face argument must be a valid path to video/image file')

    elif args['face'].split('.')[1] in ['jpg', 'png', 'jpeg']:
        full_frames = [cv2.imread(args['face'])]
        fps = args['fps']

    else:
        video_stream = cv2.VideoCapture(args['face'])
        fps = video_stream.get(cv2.CAP_PROP_FPS)

        print('Reading video frames...')

        full_frames = []
        while 1:
            still_reading, frame = video_stream.read()
            if not still_reading:
                video_stream.release()
                break

            # aspect_ratio = frame.shape[1] / frame.shape[0]
            # frame = cv2.resize(frame, (int(args['out_height'] * aspect_ratio), args['out_height']))
            if args['resize_factor'] > 1:
                frame = cv2.resize(frame, (frame.shape[1]//args['resize_factor'], frame.shape[0]//args['resize_factor']))

            if args['rotate']:
                frame = cv2.rotate(frame, cv2.cv2.ROTATE_90_CLOCKWISE)

            y1, y2, x1, x2 = args['crop']
            if x2 == -1: x2 = frame.shape[1]
            if y2 == -1: y2 = frame.shape[0]

            frame = frame[y1:y2, x1:x2]

            full_frames.append(frame)

    print ("Number of frames available for inference: "+str(len(full_frames)))

    if not args['audio'].endswith('.wav'):
        print('Extracting raw audio...')
        # command = 'ffmpeg -y -i {} -strict -2 {}'.format(args[audio, 'temp/temp.wav')
        # subprocess.call(command, shell=True)
        subprocess.check_call([
            "ffmpeg", "-y",
            "-i", args['audio'],
            "temp/temp.wav",
        ])
        args['audio'] = 'temp/temp.wav'

    wav = audio.load_wav(args['audio'], 16000)
    mel = audio.melspectrogram(wav)
    print(mel.shape)

    if np.isnan(mel.reshape(-1)).sum() > 0:
        raise ValueError('Mel contains nan! Using a TTS voice? Add a small epsilon noise to the wav file and try again')

    mel_chunks = []
    mel_idx_multiplier = 80./fps
    i = 0
    while 1:
        start_idx = int(i * mel_idx_multiplier)
        if start_idx + mel_step_size > len(mel[0]):
            mel_chunks.append(mel[:, len(mel[0]) - mel_step_size:])
            break
        mel_chunks.append(mel[:, start_idx : start_idx + mel_step_size])
        i += 1

    print("Length of mel chunks: {}".format(len(mel_chunks)))

    full_frames = full_frames[:len(mel_chunks)]
    batch_size = args['wav2lip_batch_size']
    gen = datagen(full_frames.copy(), mel_chunks)

    s = time()
    for i, (img_batch, mel_batch, frames, coords) in enumerate(tqdm(gen, 
											total=int(np.ceil(float(len(mel_chunks))/batch_size)))):

    # for i, (img_batch, mel_batch, frames, coords) in enumerate(tqdm(gen,
    #                                         total=int(np.ceil(float(len(mel_chunks))/batch_size)))):
        
        if i == 0:
            model = load_model(args['checkpoint_path'])
			# print ("Model loaded")

            frame_h, frame_w = full_frames[0].shape[:-1]
            out = cv2.VideoWriter('temp/result.avi',
                                    cv2.VideoWriter_fourcc(*'DIVX'), fps, (frame_w, frame_h))

        img_batch = torch.FloatTensor(np.transpose(img_batch, (0, 3, 1, 2))).to(device)
        mel_batch = torch.FloatTensor(np.transpose(mel_batch, (0, 3, 1, 2))).to(device)

        with torch.no_grad():
            pred = model(mel_batch, img_batch)

        pred = pred.cpu().numpy().transpose(0, 2, 3, 1) * 255.

        for p, f, c in zip(pred, frames, coords):
            y1, y2, x1, x2 = c
            if len(c) == 0:  # Check if there are no face coordinates (no face detected)
                out.write(f)  # Write the original frame without lip-syncing
            else:
                p = cv2.resize(p.astype(np.uint8), (x2 - x1, y2 - y1))
                f[y1:y2, x1:x2] = p
                out.write(f)  
           
    out.release()
    ffmpeg_path = "D:/new/Wav2Lip/ffmpeg.exe"
    print("wav2lip prediction time:", time() - s)
    command = '{} -y -i {} -i {} -strict -2 -q:v 1 {}'.format(ffmpeg_path,args['audio'], 'temp/result.avi', final_output_directory)
    subprocess.call(command, shell=platform.system() != 'Windows')
    # subprocess.check_call([
    #     "ffmpeg", "-y",
    #     # "-vsync", "0", "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
    #     "-i", "temp/result.avi",
    #     "-i", args['audio'],
    #     # "-c:v", "h264_nvenc",
    #     args['outfile'],
    # ])

