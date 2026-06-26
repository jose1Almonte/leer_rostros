# import cv2

# face_cascade = cv2.CascadeClassifier("haarcascade_frontalface_default.xml")

# cap = cv2.VideoCapture(0)

# while True:
#     _, img = cap.read()
#     gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
#     faces = face_cascade.detectMultiScale(gray,1.1,4)
#     for (x,y,w,h) in faces:
#         cv2.rectangle(img, (x,y),(x*w,y*h),(255,0,0),2)
#     cv2.imshow("img",img)
#     k = cv2.waitKey(30)
#     if k == 27:
#         break

# cap.release()


import cv2
import numpy as np

faceClassif = cv2.CascadeClassifier("haarcascade_frontalface_default.xml")

image = cv2.imread('oficina.png')
gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

faces = faceClassif.detectMultiScale(gray,scaleFactor=1.1,minNeighbors=5,minSize=(30,30),maxSize=(200,200))

for (x,y,w,h) in faces:
    cv2.rectangle(image,(x,y),(x+w,y+h),(0,255,0),2)

# cv2.namedWindow('image', cv2.WINDOW_NORMAL)

cv2.imshow('image',image)
cv2.waitKey(0)
cv2.destroyAllWindows()