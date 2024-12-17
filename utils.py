import os
import boto3
import shutil
import logging
import subprocess

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def load_yaml_config(config_path: str) -> dict:
    """
    Load and return configuration from a YAML file.
    
    Args:
        config_path (str): Path to the YAML config file.
    
    Returns:
        dict: Configuration dictionary loaded from the YAML file.
    
    Raises:
        FileNotFoundError: If the config file doesn't exist
        yaml.YAMLError: If the YAML file is invalid
    """
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        return config
    except FileNotFoundError:
        raise FileNotFoundError(f"Config file not found at: {config_path}")
    except yaml.YAMLError as e:
        raise yaml.YAMLError(f"Error parsing YAML file: {e}")


def create_lambda_layer(packages=None):
    if packages is None:
        packages = ['requests'] 
    try:
        # Create directory structure
        layer_dir = "lambda_layer"
        python_lib_dir = os.path.join(layer_dir, "python/lib/python3.9/site-packages")
        if os.path.exists(layer_dir):
            shutil.rmtree(layer_dir)
        os.makedirs(python_lib_dir)     
        # Install all specified packages into the directory
        for package in packages:
            subprocess.check_call([
                "pip",
                "install",
                package,
                "-t",
                python_lib_dir
            ])
        shutil.make_archive("lambda_layer", 'zip', layer_dir)
        shutil.rmtree(layer_dir)
    except Exception as e:
        logger.error(f"Error creating lambda layer: {str(e)}")
        raise e
    return "lambda_layer.zip"

# Using boto3 to create the layer
def publish_layer(layer_name):
    lambda_client = boto3.client('lambda')
    with open('lambda_layer.zip', 'rb') as zip_file:
        response = lambda_client.publish_layer_version(
            LayerName=layer_name,
            Description='Layer containing packages to run the lambda function within the action group of the agent',
            Content={
                'ZipFile': zip_file.read()
            },
            CompatibleRuntimes=['python3.9'],
            CompatibleArchitectures=['x86_64']
        )
    return response['LayerVersionArn']
