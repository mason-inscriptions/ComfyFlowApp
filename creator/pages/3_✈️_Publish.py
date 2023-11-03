from loguru import logger
import json
import os
import base64
from urllib.parse import urlparse
import streamlit as st
import modules.page as page
from modules import get_sqlite_instance, get_comfyflow_model_info, get_comfyflow_object_info, publish_app
from modules.sqlitehelper import AppStatus
from streamlit_extras.row import row
from streamlit_extras.switch_page_button import switch_page
from huggingface_hub import hf_hub_url, get_hf_file_metadata

MODEL_SEP = '##'

def check_model_url(model_url):
    # parse model info from download url, 
    # eg: https://huggingface.co/segmind/SSD-1B/blob/main/unet/diffusion_pytorch_model.fp16.safetensors

    # only support huggingface model hub
    parsed_url = urlparse(model_url)
    path_parts = parsed_url.path.split('/')
    repo_id = '/'.join(path_parts[1:3])  
    if len(path_parts[5:-1]) > 0:
        subfolder = os.path.sep.join(path_parts[5:-1])  
    else:
        subfolder = None
    filename = path_parts[-1]  # 最后一个元素是filename
    logger.debug(f"repo_id: {repo_id}, subfolder: {subfolder}, filename: {filename}")
    if repo_id and filename:
        hf_url = hf_hub_url(repo_id, filename, subfolder=subfolder)
        if hf_url:
            hf_meta = get_hf_file_metadata(url=hf_url)
            logger.debug(f"hf_meta, {hf_meta}")
            return hf_meta
        


logger.info("Loading publish page")
page.page_init()

with st.container():
    with page.stylable_button_container():
        header_row = row([0.85, 0.15], vertical_align="top")
        header_row.title("✈️ Publish and share to friends")
        back_button = header_row.button("Back Workspace", help="Back to your workspace", key='publish_back_workspace')
        if back_button:
            switch_page("Workspace")

    
    apps = get_sqlite_instance().get_all_apps()
    app_name_map = {app.name: app for app in apps if app.status == AppStatus.PREVIEWED.value or app.status == AppStatus.PUBLISHED.value} 
    preview_app_opts = list(app_name_map.keys())
    if len(preview_app_opts) == 0:
        st.warning("No app is available to publish, please preview app first.")
        st.stop()
    else:
        with st.container():

            st.selectbox("My Apps", options=preview_app_opts, key='publish_select_app', help="Select a app to publish.")

            app = app_name_map[st.session_state['publish_select_app']]
            app_name = app.name
            api_data_json = json.loads(app.api_conf)
            app_data_json = json.loads(app.app_conf)

            # config app nodes
            with st.expander("Parse comfyui node info", expanded=True):
                object_info = get_comfyflow_object_info()
                if object_info:
                    for node_id in api_data_json:
                        inputs = api_data_json[node_id]['inputs']
                        class_type = api_data_json[node_id]['class_type']
                        if class_type in object_info:
                            st.write(f":green[Check node info\, {node_id}\:{class_type}]")
                        else:
                            st.write(f":red[Node info not found\, {node_id}\:{class_type}]")
                            st.session_state['publish_invalid_node'] = True
                else:
                    st.warning("Get comfyflow object_info error")
                    st.stop()

            # config app models
            with st.expander("Config app models", expanded=True):
                object_model = get_comfyflow_model_info()
                if object_model:
                    for node_id in api_data_json:
                        inputs = api_data_json[node_id]['inputs']
                        class_type = api_data_json[node_id]['class_type']
                        if class_type in object_model:
                            model_name_path = object_model[class_type]
                            input_model_row = row([0.5, 0.5])
                            for param in inputs:
                                if param in model_name_path:
                                    model_input_name = f"{node_id}:{class_type}:{inputs[param]}"
                                    input_model_row.text_input("App model name", value=model_input_name, help="App model name")
                                    input_model_row.text_input("Input model url", key=model_input_name, help="Input model url of huggingface model hub")
                else:
                    st.warning("Get comfyflow model_info error")
                    st.stop()
                                                        
            publish_button = st.button("Publish", key='publish_button', type='primary', 
                      help="Publish app to store and share with your friends")
            if publish_button:
                if 'publish_invalid_node' in st.session_state:
                    st.warning("Invalid node, please check node info.")
                else:
                    # check model url
                    model_size = 0
                    models = {}
                    for node_id in api_data_json:
                        inputs = api_data_json[node_id]['inputs']
                        class_type = api_data_json[node_id]['class_type']
                        if class_type in object_model:
                            model_node_inputs = {}
                            model_name_path = object_model[class_type]
                            for param in inputs:
                                if param in model_name_path:
                                    model_path = model_name_path[param]
                                    model_input_name = f"{node_id}:{class_type}:{inputs[param]}"
                                    if not st.session_state[model_input_name]:
                                        st.warning(f"Please input model url for {model_input_name}")
                                        st.stop()
                                    else:
                                        model_url = st.session_state[model_input_name]
                                        model_meta = check_model_url(model_url)
                                        if model_meta:
                                            model_node_inputs[param] = {
                                                "url": model_url,
                                                "size": model_meta.size,
                                                "path": model_path,
                                            }
                                        else:
                                            st.warning(f"Invalid model url for {model_input_name}")
                                            st.stop()
                            if model_node_inputs:
                                models[node_id] = {"inputs": model_node_inputs}
                            
                    
                    # update app_conf and status
                    app_data_json['models'] = models
                    app_data = json.dumps(app_data_json)
                    logger.info(f"update models, {app_data}")
                    get_sqlite_instance().update_app_publish(app_name, app_data)

                    # convert image to base64
                    image_base64 = base64.b64encode(app.image).decode('utf-8')

                    # call api to publish app
                    ret = publish_app(app.name, app.description, image_base64, app_data, app.api_conf, app.template, AppStatus.PUBLISHED.value)
                    if ret:
                        st.success("Publish success, you can share this app with your friends.")
                    else:
                        st.error("Publish app error")
