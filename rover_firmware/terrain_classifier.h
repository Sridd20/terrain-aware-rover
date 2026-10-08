#pragma once
#include <cstdarg>
namespace Eloquent {
    namespace ML {
        namespace Port {
            class DecisionTree {
                public:
                    /**
                    * Predict class for features vector
                    */
                    int predict(float *x) {
                        if (x[0] <= 0.7491919994354248) {
                            if (x[2] <= 4.5) {
                                return 3;
                            }

                            else {
                                return 0;
                            }
                        }

                        else {
                            if (x[1] <= 7.537841320037842) {
                                if (x[2] <= 40.5) {
                                    if (x[2] <= 38.5) {
                                        if (x[0] <= 0.8948599994182587) {
                                            return 3;
                                        }

                                        else {
                                            return 3;
                                        }
                                    }

                                    else {
                                        if (x[1] <= 6.136108636856079) {
                                            return 3;
                                        }

                                        else {
                                            return 1;
                                        }
                                    }
                                }

                                else {
                                    if (x[0] <= 1.598208487033844) {
                                        if (x[2] <= 46.0) {
                                            return 2;
                                        }

                                        else {
                                            return 2;
                                        }
                                    }

                                    else {
                                        if (x[1] <= 7.071777582168579) {
                                            return 1;
                                        }

                                        else {
                                            return 1;
                                        }
                                    }
                                }
                            }

                            else {
                                if (x[2] <= 31.0) {
                                    return 3;
                                }

                                else {
                                    if (x[0] <= 1.5612415075302124) {
                                        if (x[1] <= 7.78216552734375) {
                                            return 1;
                                        }

                                        else {
                                            return 2;
                                        }
                                    }

                                    else {
                                        return 1;
                                    }
                                }
                            }
                        }
                    }

                    /**
                    * Predict readable class name
                    */
                    const char* predictLabel(float *x) {
                        return idxToLabel(predict(x));
                    }

                    /**
                    * Convert class idx to readable name
                    */
                    const char* idxToLabel(uint8_t classIdx) {
                        switch (classIdx) {
                            case 0:
                            return "carpet";
                            case 1:
                            return "gravel";
                            case 2:
                            return "pavement";
                            case 3:
                            return "tile";
                            default:
                            return "Houston we have a problem";
                        }
                    }

                protected:
                };
            }
        }
    }