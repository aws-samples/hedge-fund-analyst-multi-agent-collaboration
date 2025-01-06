# Build Streamlit UI in Amazon SageMaker Studio



We will use [Streamlit](https://github.com/streamlit/streamlit) to build a UI for our agents and run it inside SageMaker Studio. 

## Prerequisites
- Access to Amazon SageMaker Studio

## Step 1: SageMaker Studio

This solution has been tested on SageMaker Studio with JupyterLab 3. For more on running Streamlit inside SageMaker Studio, please refer to this [blog post](https://aws.amazon.com/blogs/machine-learning/build-streamlit-apps-in-amazon-sagemaker-studio/). 

## Step 2: Install Dependencies
Make sure you have Streamlit installed. 

```python
!pip install --no-cache-dir -r requirements.txt
```
Note: The requirements.txt file contains all necessary dependencies for this project.

## Step 3: Run Streamlit Demo and Create Shareable Link

View the multi-agent demo by running the command below in the System Terminal. 

`bash run.sh`
