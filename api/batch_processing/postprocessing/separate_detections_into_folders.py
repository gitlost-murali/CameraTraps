#
# separate_detections_into_folders.py
#
# Given a .json file with batch processing results, separate the files in that
# set of results into folders that contain animals/people/vehicles/nothing, 
# according to per-class thresholds.
#
# Places images that are above threshold for multiple classes into 'multiple'
# folder.
#
# Image files are copied, not moved.
#
# Preserves relative paths within each of those folders; cannot be used with .json
# files that have absolute paths in them.
#
# For example, if your .json file has these images:
#
# a/b/c/1.jpg
# a/b/d/2.jpg
# a/b/e/3.jpg
# a/b/f/4.jpg
#
# And let's say:
#
# * The results say that the first three images are empty/person/vehicle, respectively
# * The fourth image is above threshold for "animal" and "person"
# * You specify an output base folder of c:\out
#
# You will get the following files:
#
# c:\out\empty\a\b\c\1.jpg
# c:\out\people\a\b\d\2.jpg
# c:\out\vehicles\a\b\e\3.jpg
# c:\out\multiple\a\b\f\4.jpg
#
# Hard-coded to work with MDv3 and MDv4 output files.  Not currently future-proofed
# past the classes in MegaDetector v4, not currently ready for species-level classification.  
#


#%% Constants and imports

import argparse
import json
import os
import shutil
import sys
from multiprocessing.pool import ThreadPool
from functools import partial
        
from tqdm import tqdm

from ct_utils import args_to_object

friendly_folder_names = {'animal':'animals','person':'people','vehicle':'vehicles'}

# Occasionally we have near-zero confidence detections associated with COCO classes that
# didn't quite get squeezed out of the model in training.  As long as they're near zero
# confidence, we just ignore them.
invalid_category_epsilon = 0.00001


#%% Options class

class SeparateDetectionsIntoFoldersOptions:
    
    # Inputs
    default_threshold = 0.725
    category_name_to_threshold = {} # {'animal':0.5}
    
    n_threads = 1
    
    allow_existing_directory = False
    
    results_file = None
    base_input_folder = None
    base_output_folder = None
        
    # Dictionary mapping categories (plus 'multiple' and 'empty') to output folders
    category_name_to_folder = None
    category_id_to_category_name = None
    
    
#%% Support functions
    
def path_is_abs(p): return (len(p) > 1) and (p[0] == '/' or p[1] == ':')
    
def process_detection(d,options):

    relative_filename = d['file']
    detections = d['detections']
    
    category_name_to_max_confidence = {}
    category_names = options.category_id_to_category_name.values()
    for category_name in category_names:
        category_name_to_max_confidence[category_name] = 0.0
        
    # Find the maximum confidence for each category
    #
    # det = detections[0]
    for det in detections:
        
        category_id = det['category']
        
        # For zero-confidence detections, we occasionally have leftover goop
        # from COCO classes
        if category_id not in options.category_id_to_category_name:
            print('Warning: unrecognized category {} in file {}'.format(
                category_id,relative_filename))
            # assert det['conf'] < invalid_category_epsilon
            continue
            
        category_name = options.category_id_to_category_name[category_id]
        if det['conf'] > category_name_to_max_confidence[category_name]:
            category_name_to_max_confidence[category_name] = det['conf']
    
    # Count the number of thresholds exceeded
    categories_above_threshold = []
    for category_name in category_names:
        
        threshold = options.default_threshold
        
        # Do we have a custom threshold for this category?
        if category_name in options.category_name_to_threshold:
            threshold = options.category_name_to_threshold[threshold]
            
        max_confidence_this_category = category_name_to_max_confidence[category_name]
        if max_confidence_this_category > threshold:
            categories_above_threshold.append(category_name)
    
    target_folder = ''
    
    # If this is above multiple thresholds
    if len(categories_above_threshold) > 1:
        target_folder = options.category_name_to_folder['multiple']

    elif len(categories_above_threshold) == 0:
        target_folder = options.category_name_to_folder['empty']
        
    else:
        target_folder = options.category_name_to_folder[categories_above_threshold[0]]
        
            
    source_path = os.path.join(options.base_input_folder,relative_filename)
    assert os.path.isfile(source_path), 'Cannot find file {}'.format(source_path)
    
    target_path = os.path.join(target_folder,relative_filename)
    target_dir = os.path.dirname(target_path)
    os.makedirs(target_dir,exist_ok=True)
    shutil.copyfile(source_path,target_path)
    
# ...def process_detection()
    
    
#%% Main function
    
def separate_detections_into_folders(options):

    # Create output folder if necessary
    if (os.path.isdir(options.base_output_folder)) and \
        (len(os.listdir(options.base_output_folder) ) > 0):
        if options.allow_existing_directory:
            print('Warning: target folder exists and is not empty... did you mean to delete an old version?')
        else:
            raise ValueError('Target folder exists and is not empty')
    os.makedirs(options.base_output_folder,exist_ok=True)    
    
    # Load detection results    
    results = json.load(open(options.results_file))
    detections = results['images']
    
    for d in detections:
        fn = d['file']
        assert not path_is_abs(fn), 'Cannot process results with absolute image paths'
        
    print('Processing {} detections'.format(len(detections)))
    
    detection_categories = results['detection_categories']
    options.category_id_to_category_name = detection_categories
    
    # Map class names to output folders
    options.category_name_to_folder = {}
    options.category_name_to_folder['empty'] = os.path.join(options.base_output_folder,'empty')
    options.category_name_to_folder['multiple'] = os.path.join(options.base_output_folder,'multiple')
    
    for category_name in detection_categories.values():
        folder_name = category_name
        if category_name in friendly_folder_names:
            folder_name = friendly_folder_names[category_name]
        options.category_name_to_folder[category_name] = \
            os.path.join(options.base_output_folder,folder_name)
    
    for folder in options.category_name_to_folder.values():
        os.makedirs(folder,exist_ok=True)            
        
    if options.n_threads <= 1:
    
        # i_image = 7600; d = detections[i_image]; print(d)
        for d in tqdm(detections):
            process_detection(d,options)
        
    else:
        
        pool = ThreadPool(options.n_threads)        
        
        process_detection_with_optios = partial(process_detection, options=options)
        results = list(tqdm(pool.imap(process_detection_with_optios, detections), total=len(detections)))
        
        
#%% Interactive driver
        
if False:

    pass

    #%%
    
    options = SeparateDetectionsIntoFoldersOptions()    
    options.results_file = r"G:\x\x-20200407\combined_api_outputs\x-20200407_detections.filtered_rde_0.60_0.85_5_0.05.json"
    options.base_input_folder = "z:\\"
    options.base_output_folder = r"E:\x-out"
    options.n_threads = 100
    options.default_threshold = 0.8
    options.allow_existing_directory = False
    
    #%%
    
    separate_detections_into_folders(options)
    
    
    #%% Find a particular file
    
    results = json.load(open(options.results_file))
    detections = results['images']    
    filenames = [d['file'] for d in detections]
    i_image = filenames.index('for_Azure\HL0913\RCNX1896.JPG')
    
    
#%% Command-line driver   

# python api\batch_processing\postprocessing\separate_detections_into_folders.py "d:\temp\rspb_mini.json" "d:\temp\demo_images\rspb_2018_2019_mini" "d:\temp\separation_test" --nthreads 2


def main():
    
    parser = argparse.ArgumentParser()
    parser.add_argument('results_file', type=str, help='Input .json filename')
    parser.add_argument('base_input_folder', type=str, help='Input image folder')
    parser.add_argument('base_output_folder', type=str, help='Output image folder')
    
    options = SeparateDetectionsIntoFoldersOptions()
    parser.add_argument('--animal_threshold', type=float, default=options.animal_threshold, 
                        help='Confidence threshold for the animal category')
    parser.add_argument('--human_threshold', type=float, default=options.human_threshold, 
                        help='Confidence threshold for the human category')
    parser.add_argument('--vehicle_threshold', type=float, default=options.vehicle_threshold, 
                        help='Confidence threshold for vehicle category')
    parser.add_argument('--nthreads', type=int, default=options.n_threads, 
                        help='Number of threads to use for parallel operation')
    parser.add_argument('--allow_existing_directory', action='store_true', 
                        help='Proceed even if the target directory exists and is not empty')
    
    if len(sys.argv[1:])==0:
        parser.print_help()
        parser.exit()
        
    args = parser.parse_args()    
    
    # Convert to an options object
    args_to_object(args, options)
    
    separate_detections_into_folders(options)
    
if __name__ == '__main__':
    
    main()
    