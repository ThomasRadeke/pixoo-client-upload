"""
Pixoo Client with gallery uploading support
"""

import sys
import socket
import os
from time import sleep
from PIL import Image
from math import log10, ceil

class Pixoo(object):

    CMD_SET_BOX_COLOR = 0x44 #68 - draw single frame
    CMD_SET_BOX_MODE = 0x45 #69
    CMD_SET_MUL_BOX_COLOR = 0x49 # 73 - draw animation
    CMD_DRAWING_ENCODE_PIC = 0x5b #91
    CMD_SET_SYSTEM_BRIGHTNESS = 0x74 #116
    CMD_SET_USER_GIF = 0xb1 #177 - upload to gallery
    CMD_MISC = 0xbd #189 - used for various commands
    
    # secondary commands when used together with CMD_MISC
    CMD_MISC_DELETE_GALLERY = 0x16 # delete an entire gallery on the device
    CMD_MISC_SET_GALLERY = 0x17 # switch to a specific gallery

    BOX_MODE_CLOCK=0
    BOX_MODE_COLOR=1
    BOX_MODE_HOT=2
    BOX_MODE_SPECIAL=3
    BOX_MODE_MUSIC=4
    BOX_MODE_USERDEFINED=5
    BOX_MODE_WATCH = 6
    BOX_MODE_SCORE=7
    
    # Delay between sent packets, in whole seconds. Increase this if your upload fails.
    upload_delay = 0.01

    instance = None
    
    def hex_str(self, string):
        """
        Convert a string to a hex representation.
        """
        result = ''
        for char in string:
            result = result + ("%0.2X" % char)
        return result

    def __init__(self, mac_address):
        """
        Constructor
        """
        self.mac_address = mac_address
        self.btsock = None


    @staticmethod
    def get():
        if Pixoo.instance is None:
            Pixoo.instance = Pixoo(Pixoo.BDADDR)
            Pixoo.instance.connect()
        return Pixoo.instance

    def connect(self):
        """
        Connect to SPP.
        """
        self.btsock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        self.btsock.connect((self.mac_address, 1))


    def __spp_frame_checksum(self, args):
        """
        Compute frame checksum
        """
        return sum(args[1:])&0xffff


    def __spp_frame_encode(self, cmd, args):
        """
        Encode frame for given command and arguments (list).
        """
        payload_size = len(args) + 3

        # create our header
        frame_header = [0x01, payload_size & 0xff, (payload_size >> 8) & 0xff, cmd]

        # concatenate our args (byte array)
        frame_buffer = frame_header + args

        # compute checksum (first byte excluded)
        cs = self.__spp_frame_checksum(frame_buffer)

        # create our suffix (including checksum)
        frame_suffix = [cs&0xff, (cs>>8)&0xff, 2]
        
        final_frame = frame_buffer+frame_suffix
        
        # uncomment to see the hex stream that gets sent.
        print(self.hex_str(final_frame))
        
        sleep(self.upload_delay)
        
        # return output buffer
        return final_frame


    def send(self, cmd, args):
        """
        Send data to SPP.
        """
        spp_frame = self.__spp_frame_encode(cmd, args)
        if self.btsock is not None:
            nb_sent = self.btsock.send(bytes(spp_frame))


    def set_system_brightness(self, brightness):
        """
        Set system brightness (1-100, 0 turns the screen off).
        """
        brightness = int(brightness) % 101
        self.send(Pixoo.CMD_SET_SYSTEM_BRIGHTNESS, [brightness&0xff])


    def set_box_mode(self, boxmode, visual=0, mode=0):
        """
        Set box mode.
        """
        self.send(Pixoo.CMD_SET_BOX_MODE, [int(boxmode)&0xff, visual&0xff, mode&0xff])


    def set_color(self, r,g,b):
        """
        Set color.
        """
        self.send(0x6f, [r&0xff, g&0xff, b&0xff])

    def encode_image(self, filepath):
        img = Image.open(filepath)
        return self.encode_raw_image(img)

    def encode_raw_image(self, img):
        """
        Encode a 16x16 image.
        """
        # ensure image is 16x16
        w,h = img.size
        if w == h:
            # resize if image is too big
            if w > 16:
                img = img.resize((16,16))

            # create palette and pixel array
            pixels = []
            palette = []
            for y in range(16):
                for x in range(16):
                    pix = img.getpixel((x,y))
                    if isinstance(pix, int):
                        pix = [pix, pix, pix]
                        
                    if len(pix) == 4:
                        r,g,b,a = pix
                    elif len(pix) == 3:
                        r,g,b = pix
                    if (r,g,b) not in palette:
                        palette.append((r,g,b))
                        idx = len(palette)-1
                    else:
                        idx = palette.index((r,g,b))
                    pixels.append(idx)

            # encode pixels
            bitwidth = ceil(log10(len(palette))/log10(2))
            nbytes = ceil((256*bitwidth)/8.)
            encoded_pixels = [0]*nbytes

            encoded_pixels = []
            encoded_byte = ''
            for i in pixels:
                encoded_byte = bin(i)[2:].rjust(bitwidth, '0') + encoded_byte
                if len(encoded_byte) >= 8:
                        encoded_pixels.append(encoded_byte[-8:])
                        encoded_byte = encoded_byte[:-8]
            encoded_data = [int(c, 2) for c in encoded_pixels]
            encoded_palette = []
            for r,g,b in palette:
                encoded_palette += [r,g,b]
            returndata = (len(palette), encoded_palette, encoded_data)
            return returndata
        else:
            print('[!] Image must be square.')

    def draw_gif(self, filepath, speed=100):
        """
        Parse GIF file and draw as animation.
        """
        # encode frames
        frames = []
        timecode = speed
        reset_palette = 0
        anim_gif = Image.open(filepath)
        for n in range(anim_gif.n_frames):
            anim_gif.seek(n)
            speed = anim_gif.info['duration']
            num_colors, palette, pixel_data = self.encode_raw_image(anim_gif.convert(mode='RGB'))
            frame_size = 7 + len(pixel_data) + len(palette)
            num_colors = num_colors % 256
            frame_header = [0xAA, frame_size&0xff, (frame_size>>8)&0xff, timecode&0xff, (timecode>>8)&0xff, reset_palette, num_colors]
            frame = frame_header + palette + pixel_data
            frames += frame

        # send animation
        nchunks = ceil(len(frames)/200.)
        total_size = len(frames)
        for i in range(nchunks):
            chunk = [total_size&0xff, (total_size>>8)&0xff, i]
            self.send(Pixoo.CMD_SET_MUL_BOX_COLOR, chunk+frames[i*200:(i+1)*200])
    
    def upload_delete_gallery(self, gallery_index = 0):
        self.send(pixoo.CMD_MISC, [pixoo.CMD_MISC_DELETE_GALLERY, gallery_index & 0xff])
    
    def set_gallery(self, gallery_index):
        # the Pixoo only supports 3 galleries, so make sure we're sending valid commands
        gallery_index = gallery_index % 3
        #self.set_box_mode(Pixoo.BOX_MODE_SPECIAL)
        self.send(pixoo.CMD_MISC_SET_GALLERY, [gallery_index & 0xff])
    
    def upload_to_gallery(self, filepaths, gallery_index = 0):
        print("Preparing upload to gallery", gallery_index+1)
        # prepare upload
        self.send(Pixoo.CMD_SET_USER_GIF, [0x00, 0x00, gallery_index & 0xff])
        
        frames = []
        n = 0
        for filepath in filepaths:
            print("["+str(n+1)+"]", filepath)
            # Because of bugs in the Pixoo firmware, mixing the upload
            # methods of still pictures and GIFs screws up their display
            # duration. However, treating still images as single-frame
            # GIFs works just fine.
            fileextension = os.path.splitext(filepath)[-1].lower()
            
            if fileextension in (".png", ".jpg", ".gif"):
                frames += self.prepare_animation(filepath, n)
            n = n+1
            
        # send all frames at once
        max_chunk_size = 200
        nchunks = ceil(len(frames)/float(max_chunk_size))
        for i in range(nchunks):
            chunk_data = frames[i*max_chunk_size:(i+1)*max_chunk_size]
            chunk_size = len(chunk_data)
            chunk_header = [0x01, chunk_size&0xff, (chunk_size>>8)&0xff]
            self.send(Pixoo.CMD_SET_USER_GIF, chunk_header+chunk_data)
        
        print("Finished uploading to gallery", gallery_index+1)
        print("Uploaded", ceil(len(frames)/2), "bytes")
        # finish upload
        self.send(Pixoo.CMD_SET_USER_GIF, [0x02])
        
            
    def draw_image(self, filepath):
        fileextension = os.path.splitext(filepath)[-1].lower()
        if fileextension in (".gif"):
            print("Drawing animation...")
            
            frames = self.prepare_animation(filepath, 0)
            # send all frames at once
            max_chunk_size = 200
            nchunks = ceil(len(frames)/float(max_chunk_size))
            for i in range(nchunks):
                chunk_data = frames[i*max_chunk_size:(i+1)*max_chunk_size]
                chunk_size = len(chunk_data)
                chunk_header = [chunk_size&0xff, (chunk_size>>8)&0xff, i]
                self.send(Pixoo.CMD_SET_MUL_BOX_COLOR, chunk_header+chunk_data)
            #self.draw_gif(filepath)
        elif fileextension in (".png", ".jpg"):
            print("Drawing picture...")
            self.draw_pic(filepath)
        else:
            print("Unsupported file extension.")
    
    def prepare_animation(self, filepath, image_index):
        """
        Parse image file and prepare it for uploading to device. Supports both single images and animated GIFs. Speed is in milliseconds.
        """
        frames = []
        img = Image.open(filepath)
        
        #enable_palette_reusing = False # TODO; does not work yet.
        reuse_palette = 0x00
        
        # The Pixoo distinguishes separate images/animations in a gallery by the lower digit of the
        # duration byte - each image must have a distinct number, otherwise looping won't work.
        duration = 100+image_index
        
        # The Pixoo doesn't support variable-duration GIFs and displays each frame for 10 seconds instead.
        # To fix this, we're setting a fixed playback speed, but multiply the actual frames based on
        # their duration. Of course this only allows for multiples of the shortest frame duration.
        # First, we need to find out the duration of all animation frames, then determine the shortest
        # frame and then calculate a duration factor for each of the other frames.
        enable_duration_factor = True
        durations = []
        for n in range(img.n_frames):
            img.seek(n)
            if 'duration' in img.info:
                durations.append(img.info['duration']+image_index)
                
                # switch to fixed duration for debugging
                #durations.append(duration)
            else:
                durations.append(duration)

        # Find the shortest frame duration but keep in mind that
        # Pixoo's fastest playback is 25ms per frame
        shortest_duration = max(25, min(durations))
        
        for n in range(img.n_frames):
            img.seek(n)
            
            # calculate duration factor for current frame
            current_duration = durations[n]
            
            if enable_duration_factor:
                duration_factor = round(current_duration/shortest_duration)
                current_duration = shortest_duration
                #print("Frame", n,"duration factor is", duration_factor)
            else:
                duration_factor = 1
            #print("Frame", n, "duration is", current_duration)
            
            num_colors, encodedpalette, pixel_data = self.encode_raw_image(img.convert(mode='RGB'))
            
            # wrap num_colors around to 0 when all 256 colors are used
            num_colors = num_colors % 256
            
            '''
            # Enable palette reusing.
            # When enabled, each animation encodes their color palette in the first frame only.
            # This saves 3 bytes per color per frame.
            # TODO: feed generated palette from frame 1 back into encode_raw_image()
            if enable_palette_reusing:
                if n > 0:
                    reuse_palette = 0x01
                    num_colors = 0x00
                    encodedpalette = []
            '''     
            frame_size = 7 + len(pixel_data) + len(encodedpalette)
            
            frame_header = [0xAA, frame_size&0xff, (frame_size>>8)&0xff, current_duration&0xff, (current_duration>>8)&0xff, reuse_palette, num_colors]
            
            frame = frame_header + encodedpalette + pixel_data
            frames += frame*duration_factor

        return frames
    
    def draw_pic(self, filepath):
        """
        Draw encoded picture.
        """
        num_colors, palette, pixel_data = self.encode_image(filepath)
        frame_size = 7 + len(pixel_data) + len(palette)
        if num_colors == 256:
            num_colors = 0
        frame_header = [0xAA, frame_size&0xff, (frame_size>>8)&0xff, 0, 0, 0, num_colors]
        frame = frame_header + palette + pixel_data
        prefix = [0x0,0x0A,0x0A,0x04]
        self.send(Pixoo.CMD_SET_BOX_COLOR, prefix+frame)


if __name__ == '__main__':
    if len(sys.argv) >= 2:
        pixoo_baddr = sys.argv[1]
        
        command = ''
        if(len(sys.argv) >=3):
            command = sys.argv[2]
        
        if command and (len(sys.argv) >= 4):
            argument = sys.argv[3]

        pixoo = Pixoo(pixoo_baddr)
        pixoo.connect()

        # Wait a bit until connection is established. Older code says to wait 1 second, but 40ms is actually enough.
        sleep(0.04)
        
        if command == 'upload':
            arguments = sys.argv[3:]
            gallery_index = int(arguments[0])-1
            validfiles = []
            files = arguments[1:]
            for file in files:
                if os.path.isfile(file):
                  validfiles.append(file)
            
            
            # TODO: add a file size check. Tests have revealed that the Pixoo
            # has accepted animations as big as 28608 bytes per gallery (well over 200 frames).
            # Anything over that limit will make the Pixoo fail the upload
            # and switch to the first gallery.
            # Uploading several-hundred KB GIFs will actually make the Pixoo crash and reboot.
            # You could probably squeeze a few more frames in by enabling palette reusing, which
            # saves 3 bytes for each reused color per frame.
            
            if len(validfiles) > 0:
                if len(validfiles) > 16:
                    print("\nWARNING: The Pixoo only supports up to 16 images or animations per gallery. The following files will NOT be uploaded:")
                    for f in validfiles[16:]:
                        print(f)
                    print("\n")
                pixoo.upload_to_gallery(validfiles[0:16], gallery_index)

        elif command == 'setgallery':
            if int(argument) in (1,2,3):
                pixoo.set_gallery(int(argument)-1)
            else:
                print("Pixoo only has galleries 1, 2 and 3.")
        
        elif command == 'deletegallery':
            if int(argument) in (1,2,3):
                pixoo.upload_delete_gallery(int(argument)-1)
            else:
                print("Pixoo only has galleries 1, 2 and 3.")
                
        elif command == 'draw':
            if os.path.isfile(argument):
                pixoo.draw_image(argument)
            else:
                print('File "'+argument+'" does not exist.')
        elif command == 'brightness':
            pixoo.set_system_brightness(int(argument))
        elif command == 'mode':
            # disable mode switching for now. Needs more work.
            #pixoo.set_box_mode(argument)
            pass
            
    else:
        print('Usage: %s <Pixoo BT address> <command> <argument(s)>' % sys.argv[0])
