import argparse
import os
from hydrosdk import sdk


if __name__ == '__main__': 
    parser = argparse.ArgumentParser()
    parser.add_argument('--model-version', required=True)
    parser.add_argument('--model-name', required=True)
    parser.add_argument('--hydrosphere-address', required=True)
    parser.add_argument('--dev', help='Flag for development purposes', action="store_true")
    
    args = parser.parse_args()

    app_name = f'{args.model_name}-stage-app'
    model = sdk.Model.from_existing(args.model_name, args.model_version)
    application = sdk.Application.singular(app_name, model)
    
    result = application.apply(args.hydrosphere_address)
    print(result, flush=True)