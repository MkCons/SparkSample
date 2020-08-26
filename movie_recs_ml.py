#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

from pyspark.ml.evaluation import RegressionEvaluator
from pyspark.ml.recommendation import ALS
from pyspark import SparkConf, SparkContext
from pyspark.sql import SQLContext
from pyspark.sql.types import DoubleType, ArrayType, StructType, StructField, IntegerType


def init_spark_context():
    conf = SparkConf().setAppName("MovieRatings").set("spark.executor.memory", "4g")
    sc = SparkContext(conf=conf)
    return sc


if __name__ == "__main__":
    sc = init_spark_context()
    logger = sc._jvm.org.apache.log4j
    logger.LogManager.getLogger("org").setLevel(logger.Level.WARN)

    uri = "mongodb://localhost:27017/movies.movie_ratings?readPreference=primaryPreferred"

    # Read movies collection and select only fields we care about
    sqlContext = SQLContext(sc)

    df = sqlContext.read.format("com.mongodb.spark.sql").options(uri=uri).load()
    ratings = df.select('user_id', 'movie_id', 'rating')

    (training, test) = ratings.randomSplit([0.8, 0.2])

    # Build the recommendation model using ALS on the training data
    # Note we set cold start strategy to 'drop' to ensure we don't get NaN evaluation metrics
    als = ALS(maxIter=5, regParam=0.01, userCol="user_id", itemCol="movie_id", ratingCol="rating",
              coldStartStrategy="drop")
    model = als.fit(training)

    # Evaluate the model by computing the RMSE on the test data
    predictions = model.transform(test)
    evaluator = RegressionEvaluator(metricName="rmse", labelCol="rating",
                                    predictionCol="prediction")
    rmse = evaluator.evaluate(predictions)
    print("Root-mean-square error = " + str(rmse))

    # Generate top 10 movie recommendations for each user
    userRecs = model.recommendForAllUsers(10)

    # Cast Float to Double (Float is not supported by the Mongo connector)
    userRecs = userRecs.withColumn('recommendations',
                        userRecs['recommendations'].cast(ArrayType(
                            StructType(
                                [StructField('movie_id', IntegerType()),
                                 StructField('rating', DoubleType())])
                            ))
                        )

    # Write recommendations to the DB
    userRecs.write.format("com.mongodb.spark.sql.DefaultSource").options(uri=uri, collection="user_recommendations").mode("overwrite").save()

    # Generate top 10 user recommendations for each movie
    movieRecs = model.recommendForAllItems(10)

    # Generate top 10 movie recommendations for a specified set of users
    users = ratings.select(als.getUserCol()).distinct().limit(3)
    userSubsetRecs = model.recommendForUserSubset(users, 10)
    # Generate top 10 user recommendations for a specified set of movies
    movies = ratings.select(als.getItemCol()).distinct().limit(3)
    movieSubSetRecs = model.recommendForItemSubset(movies, 10)

    userRecs.show()
    movieRecs.show()
    userSubsetRecs.show()
    movieSubSetRecs.show()

    # clean up
    sc.stop()
