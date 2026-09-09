# SPDX-License-Identifier: GPL-3.0-only
"""Test doubles for scene/ui. This is NOT an iOS emulator or a runtime proof.

Only exercises Python-side control flow, coordinates, and scene graph wiring.
The real Pythonista GPU, fonts, timing and multi-touch dispatch remain untested.
"""
from types import SimpleNamespace

CONTEXTS = []
COLOR = 'white'


class Image:
    def __init__(self, width, height, commands):
        self.width, self.height, self.commands = width, height, list(commands)


class ImageContext:
    def __init__(self, width, height):
        self.width, self.height, self.commands = width, height, []
    def __enter__(self):
        CONTEXTS.append(self)
        return self
    def __exit__(self, *args):
        assert CONTEXTS.pop() is self
    def get_image(self):
        return Image(self.width, self.height, self.commands)


def set_color(color):
    global COLOR
    COLOR = color


class Path:
    def __init__(self):
        self.shape='path'
        self.points=[]
        self.line_width=1
        self.closed=False
    @classmethod
    def rect(cls, x, y, width, height):
        p=cls(); p.shape='rect'; p.points=[x,y,width,height]; return p
    @classmethod
    def oval(cls, x, y, width, height):
        p=cls(); p.shape='oval'; p.points=[x,y,width,height]; return p
    def move_to(self,x,y):self.points.append((x,y))
    def line_to(self,x,y):self.points.append((x,y))
    def close(self):self.closed=True
    def _draw(self,fill):
        assert CONTEXTS, 'Drawing without an ImageContext'
        CONTEXTS[-1].commands.append((self.shape,list(self.points),COLOR,self.line_width,fill,self.closed))
    def stroke(self):self._draw(False)
    def fill(self):self._draw(True)


class Texture:
    def __init__(self,image):
        assert isinstance(image,Image)
        self.image=image
        self.size=(image.width,image.height)
        self.filtering_mode=0


class Node:
    def __init__(self,position=(0,0),z_position=0,scale=1,x_scale=1,y_scale=1,
                 alpha=1,speed=1,parent=None):
        self.children=[]
        self.parent=None
        self.position=position
        self.z_position=z_position
        self.x_scale=x_scale*scale
        self.y_scale=y_scale*scale
        self.alpha=alpha
        self.speed=speed
        self.rotation=0
        if parent is not None:parent.add_child(self)
    def add_child(self,node):
        if node.parent:node.remove_from_parent()
        node.parent=self
        self.children.append(node)
    def remove_from_parent(self):
        if self.parent:self.parent.children.remove(self)
        self.parent=None


class SpriteNode(Node):
    def __init__(self,texture=None,size=None,color='white',blend_mode=0,**kwargs):
        super().__init__(**kwargs)
        self.texture=texture
        self.size=size or (texture.size if texture else (0,0))
        self.color=color
        self.blend_mode=blend_mode
        self.anchor_point=(.5,.5)


class LabelNode(SpriteNode):
    def __init__(self,text,font=('Helvetica',20),**kwargs):
        super().__init__(**kwargs)
        self.text=text
        self.font=font


class Scene(Node):
    def __init__(self):
        super().__init__()
        self.size=SimpleNamespace(w=390,h=844)
        self.dt=1/30
        self.t=0
        self.view=None
        self.background_color='black'


ui=SimpleNamespace(ImageContext=ImageContext,Path=Path,set_color=set_color)
scene=SimpleNamespace(Node=Node,SpriteNode=SpriteNode,LabelNode=LabelNode,
                      Scene=Scene,Texture=Texture,FILTERING_NEAREST=1)


def touch(tid,point):
    return SimpleNamespace(touch_id=tid,location=point)
