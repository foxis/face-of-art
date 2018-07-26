import os
from scipy.io import loadmat
from menpo.shape.pointcloud import PointCloud
from menpo.transform import ThinPlateSplines
import menpo.io as mio
from glob import glob
from deformation_functions import *

# landmark indices by facial feature
jaw_indices = np.arange(0, 17)
lbrow_indices = np.arange(17, 22)
rbrow_indices = np.arange(22, 27)
upper_nose_indices = np.arange(27, 31)
lower_nose_indices = np.arange(31, 36)
leye_indices = np.arange(36, 42)
reye_indices = np.arange(42, 48)
outer_mouth_indices = np.arange(48, 60)
inner_mouth_indices = np.arange(60, 68)

# flipped landmark indices
mirrored_parts_68 = np.hstack([
    jaw_indices[::-1], rbrow_indices[::-1], lbrow_indices[::-1],
    upper_nose_indices, lower_nose_indices[::-1],
    np.roll(reye_indices[::-1], 4), np.roll(leye_indices[::-1], 4),
    np.roll(outer_mouth_indices[::-1], 7),
    np.roll(inner_mouth_indices[::-1], 5)
])


def load_bb_files(bb_file_dirs):
    """load bounding box mat file"""

    bb_files_dict = {}
    for bb_file in bb_file_dirs:
        bb_mat = loadmat(bb_file)['bounding_boxes']
        num_imgs = np.max(bb_mat.shape)
        for i in range(num_imgs):
            name = bb_mat[0][i][0][0][0][0]
            bb_init = bb_mat[0][i][0][0][1] - 1  # matlab indicies
            bb_gt = bb_mat[0][i][0][0][2] - 1  # matlab indicies
            if str(name) in bb_files_dict.keys():
                print str(name), 'already exists'
            else:
                bb_files_dict[str(name)] = (bb_init, bb_gt)
    return bb_files_dict


def load_bb_dictionary(bb_dir, mode, test_data='full'):
    """create bounding box dictionary of input dataset: train/common/full/challenging"""

    if mode == 'TRAIN':
        bb_dirs = \
            ['bounding_boxes_afw.mat', 'bounding_boxes_helen_trainset.mat', 'bounding_boxes_lfpw_trainset.mat']
    else:
        if test_data == 'common':
            bb_dirs = \
                ['bounding_boxes_helen_testset.mat', 'bounding_boxes_lfpw_testset.mat']
        elif test_data == 'challenging':
            bb_dirs = ['bounding_boxes_ibug.mat']
        elif test_data == 'full':
            bb_dirs = \
                ['bounding_boxes_ibug.mat', 'bounding_boxes_helen_testset.mat', 'bounding_boxes_lfpw_testset.mat']
        elif test_data == 'training':
            bb_dirs = \
                ['bounding_boxes_afw.mat', 'bounding_boxes_helen_trainset.mat', 'bounding_boxes_lfpw_trainset.mat']
        else:
            bb_dirs = None

    if mode == 'TEST' and test_data not in ['full', 'challenging', 'common', 'training']:
        bb_files_dict = None
    else:
        bb_dirs = [os.path.join(bb_dir, dataset) for dataset in bb_dirs]
        bb_files_dict = load_bb_files(bb_dirs)

    return bb_files_dict


def center_margin_bb(bb, img_bounds, margin=0.25):
    """create new bounding box with input margin"""

    bb_size = ([bb[0, 2] - bb[0, 0], bb[0, 3] - bb[0, 1]])
    margins = (np.max(bb_size) * (1 + margin) - bb_size) / 2
    bb_new = np.zeros_like(bb)
    bb_new[0, 0] = np.maximum(bb[0, 0] - margins[0], 0)
    bb_new[0, 2] = np.minimum(bb[0, 2] + margins[0], img_bounds[1])
    bb_new[0, 1] = np.maximum(bb[0, 1] - margins[1], 0)
    bb_new[0, 3] = np.minimum(bb[0, 3] + margins[1], img_bounds[0])
    return bb_new


def crop_to_face_image(img, bb_dictionary=None, gt=True, margin=0.25, image_size=256, normalize=True):
    """crop face image using bounding box dictionary"""

    name = img.path.name
    img_bounds = img.bounds()[1]

    if bb_dictionary is None:
        bb_menpo = img.landmarks['PTS'].bounding_box().points
        bb = np.array([[bb_menpo[0, 1], bb_menpo[0, 0], bb_menpo[2, 1], bb_menpo[2, 0]]])
    else:
        if gt:
            bb = bb_dictionary[name][1]  # ground truth
        else:
            bb = bb_dictionary[name][0]  # init from face detector

    bb = center_margin_bb(bb, img_bounds, margin=margin)

    bb_pointcloud = PointCloud(np.array([[bb[0, 1], bb[0, 0]],
                                         [bb[0, 3], bb[0, 0]],
                                         [bb[0, 3], bb[0, 2]],
                                         [bb[0, 1], bb[0, 2]]]))

    face_crop = img.crop_to_pointcloud(bb_pointcloud)

    h, w = face_crop.shape
    diff = h - w
    if diff < 0:
        face_crop.pixels = np.pad(face_crop.pixels, ((0, 0), (0, -1 * diff), (0, 0)), 'reflect')
    elif diff > 0:
        face_crop.pixels = np.pad(face_crop.pixels, ((0, 0), (0, 0), (0, diff)), 'reflect')

    face_crop = face_crop.resize([image_size, image_size])

    if normalize:
        face_crop.pixels = face_crop.rescale_pixels(0., 1.).pixels

    return face_crop


def augment_face_image(img, image_size=256, crop_size=248, angle_range=30, flip=True):
    """basic image augmentation: random crop, rotation and horizontal flip"""

    # taken from MDM
    def mirror_landmarks_68(lms, im_size):
        return PointCloud(abs(np.array([0, im_size[1]]) - lms.as_vector(
        ).reshape(-1, 2))[mirrored_parts_68])

    # taken from MDM
    def mirror_image(im):
        im = im.copy()
        im.pixels = im.pixels[..., ::-1].copy()

        for group in im.landmarks:
            lms = im.landmarks[group]
            if lms.points.shape[0] == 68:
                im.landmarks[group] = mirror_landmarks_68(lms, im.shape)

        return im

    flip_rand = np.random.random() > 0.5
    #     rot_rand = np.random.random() > 0.5
    #     crop_rand = np.random.random() > 0.5
    rot_rand = True  # like ECT
    crop_rand = True  # like ECT

    if crop_rand:
        lim = image_size - crop_size
        min_crop_inds = np.random.randint(0, lim, 2)
        max_crop_inds = min_crop_inds + crop_size
        img = img.crop(min_crop_inds, max_crop_inds)

    if flip and flip_rand:
        img = mirror_image(img)

    if rot_rand:
        rot_angle = 2 * angle_range * np.random.random_sample() - angle_range
        img = img.rotate_ccw_about_centre(rot_angle)

    img = img.resize([image_size, image_size])

    return img


def augment_menpo_img_ns(img, img_dir_ns, p_ns=0):
    """texture style image augmentation using stylized copies in *img_dir_ns*"""

    img = img.copy()
    if p_ns > 0.5:
        ns_augs = glob(os.path.join(img_dir_ns, img.path.name.split('.')[0] + '*'))
        num_augs = len(ns_augs)
        if num_augs > 0:
            ns_ind = np.random.randint(0, num_augs)
            ns_aug = mio.import_image(ns_augs[ns_ind])
            ns_pixels = ns_aug.pixels
            img.pixels = ns_pixels
    return img


def augment_menpo_img_geom(img, p_geom=0):
    """geometric style image augmentation using random face deformations"""

    img = img.copy()
    if p_geom > 0.5:
        lms_geom_warp = deform_face_geometric_style(img.landmarks['PTS'].points.copy(), p_scale=p_geom, p_shift=p_geom)
        img = warp_face_image_tps(img, PointCloud(lms_geom_warp))
    return img


def warp_face_image_tps(img, new_shape):
    tps = ThinPlateSplines(new_shape, img.landmarks['PTS'])
    img_warp = img.warp_to_shape(img.shape, tps)
    img_warp.landmarks['PTS'] = new_shape
    return img_warp


def load_menpo_image_list(
        img_dir, train_crop_dir, img_dir_ns, mode, bb_dictionary=None, image_size=256, margin=0.25,
        bb_type='gt', test_data='full', augment_basic=True, augment_texture=False, p_texture=0,
        augment_geom=False, p_geom=0, verbose=False):

    def crop_to_face_image_gt(img):
        return crop_to_face_image(img, bb_dictionary, gt=True, margin=margin, image_size=image_size)

    def crop_to_face_image_init(img):
        return crop_to_face_image(img, bb_dictionary, gt=False, margin=margin, image_size=image_size)

    def augment_menpo_img_ns_rand(img):
        return augment_menpo_img_ns(img, img_dir_ns, p_ns=1. * (np.random.rand() < p_texture))

    def augment_menpo_img_geom_rand(img):
        return augment_menpo_img_geom(img, p_geom=1. * (np.random.rand() < p_geom))

    if mode is 'TRAIN':
        if train_crop_dir is None:
            img_set_dir = os.path.join(img_dir, 'training_set')
            out_image_list = mio.import_images(img_set_dir, verbose=verbose, normalize=False)
            if bb_type is 'gt':
                out_image_list = out_image_list.map(crop_to_face_image_gt)
            elif bb_type is 'init':
                out_image_list = out_image_list.map(crop_to_face_image_init)
        else:
            img_set_dir = os.path.join(img_dir, train_crop_dir)
            out_image_list = mio.import_images(img_set_dir, verbose=verbose)

        if augment_texture:
            out_image_list = out_image_list.map(augment_menpo_img_ns_rand)
        if augment_geom:
            out_image_list = out_image_list.map(augment_menpo_img_geom_rand)
        if augment_basic:
            out_image_list = out_image_list.map(augment_face_image)

    else:
        img_set_dir = os.path.join(img_dir, test_data + '_set')
        if test_data in ['full', 'challenging', 'common', 'training', 'test']:
            out_image_list = mio.import_images(img_set_dir, verbose=verbose, normalize=False)
            if bb_type is 'gt':
                out_image_list = out_image_list.map(crop_to_face_image_gt)
            elif bb_type is 'init':
                out_image_list = out_image_list.map(crop_to_face_image_init)
        else:
            out_image_list = mio.import_images(img_set_dir, verbose=verbose)

    return out_image_list


def reload_menpo_image_list(
        img_dir, train_crop_dir, img_dir_ns, mode, train_inds, image_size=256,
        augment_basic=True, augment_texture=False, p_texture=0, augment_geom=False, p_geom=0, verbose=False):
    img_menpo_list = load_menpo_image_list(
        img_dir=img_dir, train_crop_dir=train_crop_dir, img_dir_ns=img_dir_ns, mode=mode, image_size=image_size,
        augment_basic=augment_basic, augment_texture=augment_texture, p_texture=p_texture, augment_geom=augment_geom,
        p_geom=p_geom,verbose=verbose)

    img_menpo_list_train = img_menpo_list[train_inds]

    return img_menpo_list_train