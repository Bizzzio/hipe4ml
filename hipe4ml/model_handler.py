"""
Module containing the class used for wrapping the models from different
ML libraries to build a new model with common methods
"""
import inspect
import pickle

import numpy as np
from bayes_opt import BayesianOptimization
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import cross_val_score


class ModelHandler:
    """
    Class used for wrapping the models from different ML libraries to
    build a new model with common methods. Currently only XGBoost
    (through it's sklearn interface) and sklearn models are supported.

    Input
    -------------------------------------------------
    input_model: xgboost or sklearn model

    training_columns: list
        Contains the name of the features used for the training.
        Example: ['dEdx', 'pT', 'ct']

    model_params: dict
        Model hyper-parameter values. For
        example (XGBoost): max_depth, learning_rate,
        n_estimators, gamma, min_child_weight, ...
    """

    def __init__(self, input_model=None, training_columns=None, model_params=None):
        self.model = input_model
        self.training_columns = training_columns
        self.model_params = model_params

        if self.model is not None:
            self.model_string = inspect.getmodule(self.model).__name__.partition('.')[0]

            if self.model_params is None:
                self.model_params = self.model.get_params()

    def set_model_params(self, model_params):
        """
        Set the model (hyper-)parameters

        Input
        ------------------------------------
        model_params: dict
            Model hyper-parameter values. For
            example (XGBoost): max_depth, learning_rate,
            n_estimators, gamma, min_child_weight, ...
        """
        self.model_params = model_params
        self.model.set_params(**model_params)

    def get_model_params(self):
        """
        Get the model (hyper-)parameters

        Output
        ------------------------------------
        dict
            Model hyper-parameter values. For
            example (XGBoost): max_depth, learning_rate,
            n_estimators, gamma, min_child_weight, ...
        """
        return self.model.get_params()

    def set_training_columns(self, training_columns):
        """
        Set the features used for the training process

        Input
        ------------------------------------
        training_columns: list
            Contains the name of the features used for the training.
            Example: ['dEdx', 'pT', 'ct']
        """
        self.training_columns = training_columns

    def get_training_columns(self):
        """
        Get the features used for the training process

        Output
        ------------------------------------
        list
            Contains the name of the features used for the training.
            Example: ['dEdx', 'pT', 'ct']
        """

        return self.training_columns

    def get_original_model(self):
        """
        Get the original unwrapped model

        Output
        ---------------------------
        sklearn or XGBoost model
        """
        return self.model

    def get_model_module(self):
        """
        Get the string containing the name
        of the model module

        Output
        ---------------------------
        str
            Name of the model module
        """
        return self.model_string

    def fit(self, x_train, y_train):
        """
        Fit Model

        Input
        ---------------------------
        x_train: array-like, sparse matrix
            Training data

        y_train: array-like, sparse matrix
            Target data
        """
        if self.training_columns is not None:
            self.model.fit(x_train[self.training_columns], y_train)
        else:
            self.model.fit(x_train, y_train)

    def predict(self, x_test, output_margin=True):
        """
        Return model prediction for the array x_test

        Input
        --------------------------------------
        x_test: array-like, sparse matrix
            The input samples. Internally, its dtype
            will be converted to dtype=np.float32. If a
            sparse matrix is provided, it will be converted
            to a sparse csr_matrix.

        output_margin: bool
            Whether to output the raw untransformed margin value.

        Output
        ---------------------------------------
        pred: numpy_array
            Model predictions
        """
        if self.training_columns is not None:
            x_test = x_test[self.training_columns]

        if output_margin:
            if self.model_string == 'xgboost':
                pred = self.model.predict(x_test, True)
            if self.model_string == 'sklearn':
                pred = self.model.decision_function(x_test).ravel()
        else:
            pred = self.model.predict_proba(x_test)
            # in case of binary classification return only the scores of
            # the signal class
            if pred.shape[1] <= 2:
                pred = pred[:, 1]

        return pred

    def train_test_model(self, data, average='macro', multi_class_opt='raise'):
        """
        Perform the training and the testing of the model. The model performance is estimated
        using the ROC AUC metric

        Input
        ----------------------------------------------
        data: list
            Contains respectively: training
            set dataframe, training label array,
            test set dataframe, test label array

        average: string
            Option for the average of ROC AUC scores used only in case of multi-classification.
            You can choose between 'macro' and 'weighted'. For more information see
            https://scikit-learn.org/stable/modules/generated/sklearn.metrics.roc_auc_score.html#sklearn.metrics.roc_auc_score

        multi_class_opt: string
            Option to compute ROC AUC scores used only in case of multi-classification.
            The one-vs-one 'ovo' and one-vs-rest 'ovr' approaches are available
        """

        # get number of classes
        n_classes = len(np.unique(data[1]))
        print('Number of detected classes:', n_classes)

        # final training with the optimized hyperparams
        print('Training the final model: ...', end='\r')
        self.fit(data[0], data[1])
        print('Training the final model: Done!')
        print('Testing the model: ...', end='\r')
        y_pred = self.predict(data[2], output_margin=False)
        roc_score = roc_auc_score(data[3], y_pred, average=average, multi_class=multi_class_opt)
        print('Testing the model: Done!')

        print(f'ROC_AUC_score: {roc_score:.6f}')
        print('==============================')

    def evaluate_hyperparams(self, data, opt_params, scoring, nfold=5, njobs=None):
        """
        Calculate the cross-validation score for a set of hyper-parameters

        Input
        ------------------------------------------
        data: list
            Contains respectively: training
            set dataframe, training label array,
            test set dataframe, test label array

        opt_params: dict
            Hyperparameters to be optimized. For
            example: max_depth, learning_rate,
            n_estimators, gamma, min_child_weight,
            subsample, colsample_bytree

        scoring: string, callable or None
            A string (see sklearn model evaluation documentation:
            https://scikit-learn.org/stable/modules/model_evaluation.html)
            or a scorer callable object / function with signature scorer(estimator, X, y)
            which should return only a single value

        nfold: int
            Number of folds to perform the cross validation

        njobs: int or None
            Number of CPUs to use to perform computation.
            Set to -1 to use all CPUs

        Output
        ---------------------------------------------------------
        float
            Cross validation score evaluated using
            the ROC AUC metrics
        """
        opt_params = self.cast_model_params(opt_params)
        params = {**self.model_params, **opt_params}
        self.model.set_params(**params)
        if self.training_columns is not None:
            return np.mean(cross_val_score(self.model, data[0][self.training_columns], data[1],
                                           cv=nfold, scoring=scoring, n_jobs=njobs))
        return np.mean(cross_val_score(self.model, data[0], data[1], cv=nfold, scoring=scoring, n_jobs=njobs))

    def optimize_params_bayes(self, data, hyperparams_ranges, scoring, nfold=5, init_points=5,
                              n_iter=5, njobs=None):
        """
        Perform Bayesian optimization and update the model hyper-parameters
        with the best ones

        Input
        ------------------------------------------------------
        data: list
            Contains respectively: training
            set dataframe, training label array,
            test set dataframe, test label array

        hyperparams_ranges: dict
            Xgboost hyperparameter ranges(in tuples).
            For example:
            dict={
                'max_depth':(10,100)
                'learning_rate': (0.01,0.03)
            }

        scoring: string, callable or None
            A string (see sklearn model evaluation documentation:
            https://scikit-learn.org/stable/modules/model_evaluation.html)
            or a scorer callable object / function with signature scorer(estimator, X, y)
            which should return only a single value.
            In binary classification 'roc_auc' is suggested.
            In multi-classification one between ‘roc_auc_ovr’, ‘roc_auc_ovo’,
            ‘roc_auc_ovr_weighted’ and ‘roc_auc_ovo_weighted’ is suggested.
            For more information see
            https://scikit-learn.org/stable/modules/model_evaluation.html#scoring-parameter

        nfold: int
            Number of folds to calculate the cross validation error

        init_points: int
            How many steps of random exploration you want to perform.
            Random exploration can help by diversifying the exploration space

        n_iter: int
            How many steps for bayesian optimization of the target function.
            Bigger n_iter results in better description of thetarget function

        njobs: int or None
            Number of CPUs to perform computation used in the score evaluation
            with cross-validation. Set to -1 to use all CPUs
        """
        # just an helper function
        def hyperparams_crossvalidation(**kwargs):
            return self.evaluate_hyperparams(data, kwargs, scoring, nfold, njobs)
        print('')

        optimizer = BayesianOptimization(f=hyperparams_crossvalidation, pbounds=hyperparams_ranges,
                                         verbose=2, random_state=42)
        optimizer.maximize(init_points=init_points, n_iter=n_iter, acq='poi')
        print('')

        # extract and show the results of the optimization
        max_params = {key: None for key in hyperparams_ranges.keys()}
        for key in max_params.keys():
            max_params[key] = optimizer.max['params'][key]
        print(f"Best target: {optimizer.max['target']:.6f}")
        print(f'Best parameters: {max_params}')
        self.set_model_params({**self.model_params, **self.cast_model_params(max_params)})

    def cast_model_params(self, params):
        """
        Check if each model parameter is defined as integer
        and change the parameter dictionary consequently

        Input
        -----------------------------------------------------
        params: dict
            Hyperparameter values. For
            example: max_depth, learning_rate,
            n_estimators, gamma, min_child_weight,
            subsample, colsample_bytree

        Output
        -----------------------------------------------------
        params: dict
            Hyperparameter values updated
        """
        for key in params.keys():
            if isinstance(self.model.get_params()[key], int):
                params[key] = int(round(params[key]))
        return params

    def dump_original_model(self, filename, xgb_format=False):
        """
        Save the trained model into a pickle
        file. Only for xgboost models it is also given
        the possibility to save them into a .model file

        Input
        -----------------------------------------------------
        filename: str
            Name of the file in which the model is saved

        xgb_format : bool
            If True saves the xgboost model into a .model file
        """
        if xgb_format is False:
            pickle.dump(self.model, open(filename, "wb"))
        else:
            if self.model_string == 'xgboost':
                self.model.save_model(filename)
            else:
                print("File not saved: only xgboost models support the .model extension")

    def dump_model_handler(self, filename):
        """
        Save the model handler into a pickle file

        Input
        -----------------------------------------------------
        filename: str
            Name of the file in which the model is saved
        """
        pickle.dump(self, open(filename, "wb"))

    def load_model_handler(self, filename):
        """
        Load a model handler saved into a pickle file

        Input
        -----------------------------------------------------
        filename: str
            Name of the file in which the model is saved
        """
        loaded_model = pickle.load(open(filename, 'rb'))
        self.model = loaded_model.get_original_model()
        self.training_columns = loaded_model.get_training_columns()
        self.model_params = loaded_model.get_model_params()
        self.model_string = loaded_model.get_model_module()
